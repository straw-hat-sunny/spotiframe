"""Command line entry point for the album frame."""
import argparse
import os
from pathlib import Path
import signal
import sys
import time

from dotenv import load_dotenv

from .spotify import AuthenticationError, SpotifyClient, SpotifyError, TokenStore
from .signin import sign_in


def main():
    parser = argparse.ArgumentParser(description='Display the currently playing Spotify album on an Inky Impression.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('login', help='Authorize your Spotify account using PKCE')
    run = sub.add_parser('run', help='Watch playback and update the display')
    preview = run.add_mutually_exclusive_group()
    preview.add_argument('--preview', metavar='PATH', help='Write a temporary PNG preview instead of using Inky hardware')
    preview.add_argument('--browser', action='store_true', help='Open a live local browser preview instead of using Inky hardware')
    run.add_argument('--lan', action='store_true', help='Make the display preview reachable on the local network')
    run.add_argument('--reauthorize', action='store_true', help='Show the sign-in QR even when credentials are already stored')
    run.add_argument('--interval', type=int, default=30, help='Polling interval in seconds (default: 30, minimum: 10)')
    args = parser.parse_args()
    load_dotenv(Path.cwd() / '.env', override=False)
    client_id = os.environ.get('SPOTIFY_CLIENT_ID', '').strip()
    if not client_id:
        parser.error('Set SPOTIFY_CLIENT_ID in .env or your environment to your Spotify application client ID.')
    redirect = os.environ.get('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback')
    state_dir = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local' / 'state')) / 'spotiframe'
    client = SpotifyClient(client_id, redirect, TokenStore(state_dir / 'tokens.json'))
    if args.command == 'login':
        client.login()
        return
    if args.interval < 10:
        parser.error('The polling interval must be at least 10 seconds.')
    from .display import FrameController, InkyOutput, PreviewOutput
    pairing = None
    if args.browser:
        from .browser_preview import BrowserOutput
        output = BrowserOutput(lan=True, lan_host=os.environ.get('SPOTIFRAME_LAN_HOST')) if args.lan else BrowserOutput()
        pairing = output
    elif args.preview:
        output = PreviewOutput(args.preview)
    else:
        output = InkyOutput()
    if args.lan and not args.browser:
        from .browser_preview import BrowserOutput
        pairing = BrowserOutput(open_browser=False, lan=True, lan_host=os.environ.get('SPOTIFRAME_LAN_HOST'))
    controller = FrameController(output, resolution=output.resolution)
    print('Watching Spotify playback. Press Ctrl+C to stop.', flush=True)
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    failures = 0
    force_login = args.reauthorize
    try:
        while True:
            try:
                if force_login:
                    sign_in(client, controller, pairing)
                    force_login = False
                controller.update(client.playing_album())
                failures = 0
                time.sleep(args.interval)
            except AuthenticationError as exc:
                print(f'{exc}\nSpotify authorization is needed again.', file=sys.stderr, flush=True)
                try:
                    sign_in(client, controller, pairing)
                    force_login = False
                except AuthenticationError as signin_error:
                    print(f'Spotify sign-in failed: {signin_error}. Starting a new sign-in.', file=sys.stderr, flush=True)
                    time.sleep(2)
            except SpotifyError as exc:
                failures += 1
                delay = max(args.interval, min(300, 2 ** min(failures, 9)))
                print(f'{exc} Retrying in {delay} seconds.', file=sys.stderr, flush=True)
                time.sleep(delay)
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        if args.browser:
            output.close()
        elif args.preview:
            Path(args.preview).unlink(missing_ok=True)
        else:
            # E-paper retains its image after exit; remove stale Spotify content.
            controller.update(None)
        if pairing and pairing is not output:
            pairing.close()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SpotifyError, ValueError, RuntimeError, OSError, EOFError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
