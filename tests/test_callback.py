import socket
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from spotiframe.callback import CallbackReceiver


class CallbackTests(unittest.TestCase):
    def test_local_callback_rejects_wrong_state_and_accepts_the_current_attempt(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        redirect = f'http://127.0.0.1:{port}/callback'
        receiver = CallbackReceiver(redirect, 'valid-state')
        self.addCleanup(receiver.close)
        with self.assertRaises(HTTPError) as error:
            urlopen(redirect + '?code=bad&state=wrong')
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with urlopen(redirect + '?code=good&state=valid-state') as response:
            self.assertEqual(response.status, 200)
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertNotIn('good', response.read().decode())
        self.assertEqual(receiver.get(timeout=1), redirect + '?code=good&state=valid-state')

    def test_callback_does_not_serve_unrelated_paths(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        receiver = CallbackReceiver(f'http://127.0.0.1:{port}/callback', 'state')
        self.addCleanup(receiver.close)
        with self.assertRaises(HTTPError) as error:
            urlopen(f'http://127.0.0.1:{port}/.env')
        self.assertEqual(error.exception.code, 404)
        error.exception.close()

    def test_pasted_callback_must_match_redirect_and_state(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        redirect = f'http://127.0.0.1:{port}/callback'
        receiver = CallbackReceiver(redirect, 'state')
        self.addCleanup(receiver.close)
        with self.assertRaises(ValueError):
            receiver.submit(f'http://127.0.0.1:{port}/wrong?code=abc&state=state')
        receiver.submit(redirect + '?code=abc&state=state')
        self.assertEqual(receiver.get(timeout=1), redirect + '?code=abc&state=state')

    def test_https_callback_can_be_forwarded_from_a_local_tls_proxy(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        receiver = CallbackReceiver('https://frame.example.com/callback', 'state', listen_port=port)
        self.addCleanup(receiver.close)
        with urlopen(f'http://127.0.0.1:{port}/callback?code=abc&state=state') as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(receiver.get(timeout=1), 'https://frame.example.com/callback?code=abc&state=state')
