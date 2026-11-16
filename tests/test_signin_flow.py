import unittest
from types import SimpleNamespace
from unittest.mock import patch

from spotiframe.signin import sign_in


class SignInFlowTests(unittest.TestCase):
    def test_signin_displays_qr_and_exchanges_callback(self):
        class Client:
            redirect_uri = 'http://127.0.0.1:8888/callback'
            def __init__(self):
                self.completed = None
            def begin_authorization(self):
                return SimpleNamespace(url='https://accounts.spotify.com/authorize?state=abc', state='abc', verifier='secret')
            def complete_authorization(self, callback, attempt):
                self.completed = (callback, attempt.state)
        class Screen:
            def __init__(self):
                self.url = None
            def show_signin(self, url):
                self.url = url
        class Receiver:
            def __init__(self, redirect_uri, state):
                self.closed = False
            def get(self, timeout):
                return 'http://127.0.0.1:8888/callback?code=abc&state=abc'
            def close(self):
                self.closed = True
        client, screen = Client(), Screen()
        with patch('spotiframe.signin.CallbackReceiver', Receiver):
            sign_in(client, screen)
        self.assertEqual(screen.url, 'https://accounts.spotify.com/authorize?state=abc')
        self.assertEqual(client.completed, ('http://127.0.0.1:8888/callback?code=abc&state=abc', 'abc'))

class LocalAuthorizationIntegrationTests(unittest.TestCase):
    def test_local_callback_completes_pkce_flow_and_saves_credentials(self):
        import socket
        import tempfile
        from pathlib import Path
        from threading import Event, Thread
        from urllib.parse import parse_qs, urlsplit
        from urllib.request import urlopen
        from spotiframe.spotify import SpotifyClient, TokenStore
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            store = TokenStore(Path(directory) / 'tokens.json')
            client = SpotifyClient('test-client', f'http://127.0.0.1:{port}/callback', store)
            shown = Event()
            class Screen:
                def show_signin(self, url):
                    self.url = url
                    shown.set()
            screen = Screen()
            failures = []
            def run():
                try:
                    sign_in(client, screen)
                except Exception as exc:
                    failures.append(exc)
            with patch('spotiframe.spotify.request', return_value=(200, b'{"access_token":"access","refresh_token":"refresh","expires_in":3600}')):
                thread = Thread(target=run, daemon=True)
                thread.start()
                self.assertTrue(shown.wait(3), 'sign-in screen did not appear')
                state = parse_qs(urlsplit(screen.url).query)['state'][0]
                with urlopen(f'http://127.0.0.1:{port}/callback?code=example&state={state}') as response:
                    self.assertEqual(response.status, 200)
                thread.join(3)
                self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(store.load()['refresh_token'], 'refresh')
