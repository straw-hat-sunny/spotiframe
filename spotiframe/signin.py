"""Show a PKCE sign-in QR code and finish the local authorization flow."""
from queue import Empty, Full
import os
import select
import sys

from .callback import CallbackReceiver


def sign_in(client, controller, pairing=None):
    attempt = client.begin_authorization()
    if client.redirect_uri.startswith('https://'):
        receiver = CallbackReceiver(client.redirect_uri, attempt.state, listen_port=int(os.environ.get('SPOTIFRAME_CALLBACK_PORT', '8888')))
    else:
        receiver = CallbackReceiver(client.redirect_uri, attempt.state)
    try:
        qr_url = pairing.begin_signin(attempt.url, receiver) if pairing else attempt.url
        controller.show_signin(qr_url)
        print('Spotify sign-in is required. Open the sign-in page shown on the display.', flush=True)
        if sys.stdin.isatty():
            print('If the redirect opens on another device, paste its complete URL here.', flush=True)
        while True:
            try:
                callback = receiver.get(timeout=0.25)
                break
            except Empty:
                if sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
                    value = sys.stdin.readline().strip()
                    try:
                        receiver.submit(value)
                    except (ValueError, Full):
                        print('That redirect URL does not match this sign-in attempt. Try again.', file=sys.stderr, flush=True)
        client.complete_authorization(callback, attempt)
        print('Spotify connected.', flush=True)
    finally:
        if pairing:
            pairing.end_signin()
        receiver.close()
