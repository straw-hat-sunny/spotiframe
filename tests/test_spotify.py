import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from spotiframe.spotify import Album, AuthenticationError, TokenStore, authorization_request, callback_code, current_album, retry_delay


class SpotifyTests(unittest.TestCase):
    def test_authorization_uses_pkce_and_least_scope(self):
        url, verifier, state = authorization_request('test-client', 'http://127.0.0.1:8888/callback')
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['scope'], ['user-read-currently-playing'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotEqual(query['code_challenge'][0], verifier)
        self.assertEqual(query['state'], [state])

    def test_callback_rejects_mismatched_state_and_extracts_code(self):
        self.assertEqual(callback_code('http://127.0.0.1:8888/callback?code=abc&state=expected', 'expected', 'http://127.0.0.1:8888/callback'), 'abc')
        with self.assertRaises(AuthenticationError):
            callback_code('http://127.0.0.1:8888/callback?code=abc&state=wrong', 'expected', 'http://127.0.0.1:8888/callback')

    def test_token_store_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state' / 'tokens.json'
            store = TokenStore(path)
            store.save({'refresh_token': 'private'})
            self.assertEqual(store.load()['refresh_token'], 'private')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_track_album_extracted_and_paused_ignored(self):
        body = {'is_playing': True, 'currently_playing_type': 'track', 'item': {'type': 'track', 'album': {'id': 'album1', 'images': [{'url': 'https://i.scdn.co/image/full', 'width': 640, 'height': 640}], 'external_urls': {'spotify': 'https://open.spotify.com/album/album1'}}}}
        self.assertEqual(current_album(body), Album('album1', 'https://i.scdn.co/image/full'))
        body['is_playing'] = False
        self.assertIsNone(current_album(body))
        body['is_playing'] = True
        body['item']['album']['images'] = []
        self.assertIsNone(current_album(body))

    def test_retry_after_is_respected_and_backoff_increases(self):
        self.assertEqual(retry_delay('60', 0), 60)
        self.assertGreaterEqual(retry_delay('1', 3), 8)
        self.assertGreaterEqual(retry_delay(None, 2), 4)


if __name__ == '__main__':
    unittest.main()

class HTTPHandlingTests(unittest.TestCase):
    def test_429_waits_for_retry_after_then_succeeds(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread
        from unittest.mock import patch
        from spotiframe.spotify import request
        class Handler(BaseHTTPRequestHandler):
            count = 0
            def do_GET(self):
                type(self).count += 1
                if type(self).count == 1:
                    self.send_response(429)
                    self.send_header('Retry-After', '17')
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'ok')
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch('spotiframe.spotify.time.sleep') as sleep:
                result = request(f'http://127.0.0.1:{server.server_port}/')
                self.assertEqual(result, (200, b'ok'))
                sleep.assert_called_once_with(17)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_spotify_error_message_is_shown(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread
        from spotiframe.spotify import SpotifyError, request
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b'{"error":{"status":403,"message":"Account not approved"}}')
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(SpotifyError, 'Account not approved'):
                request(f'http://127.0.0.1:{server.server_port}/')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

class RefreshTests(unittest.TestCase):
    def test_refresh_keeps_previous_refresh_token_when_omitted(self):
        from unittest.mock import patch
        from spotiframe.spotify import SpotifyClient
        with tempfile.TemporaryDirectory() as directory:
            store = TokenStore(Path(directory) / 'tokens.json')
            store.save({'access_token': 'old', 'refresh_token': 'keep-me', 'expires_at': 0})
            client = SpotifyClient('client', 'http://127.0.0.1:8888/callback', store)
            with patch('spotiframe.spotify.request', return_value=(200, b'{"access_token":"new","expires_in":3600}')):
                client.refresh()
            self.assertEqual(store.load()['access_token'], 'new')
            self.assertEqual(store.load()['refresh_token'], 'keep-me')

    def test_invalid_grant_requires_reauthorization(self):
        from io import BytesIO
        from unittest.mock import patch
        from urllib.error import HTTPError
        from spotiframe.spotify import request
        response = HTTPError('https://accounts.spotify.com/api/token', 400, 'Bad Request', {}, BytesIO(b'{"error":"invalid_grant"}'))
        with patch('spotiframe.spotify.urlopen', side_effect=response):
            with self.assertRaises(AuthenticationError):
                request('https://accounts.spotify.com/api/token')

    def test_malformed_400_error_still_reports_an_http_error(self):
        from io import BytesIO
        from unittest.mock import patch
        from urllib.error import HTTPError
        from spotiframe.spotify import SpotifyError, request
        response = HTTPError('https://accounts.spotify.com/api/token', 400, 'Bad Request', {}, BytesIO(b'Not JSON'))
        with patch('spotiframe.spotify.urlopen', side_effect=response):
            with self.assertRaisesRegex(SpotifyError, 'HTTP 400'):
                request('https://accounts.spotify.com/api/token')

class ArtworkOnlyTests(unittest.TestCase):
    def test_album_art_does_not_require_an_external_link(self):
        playing = {'is_playing': True, 'currently_playing_type': 'track', 'item': {'type': 'track', 'album': {'id': 'album1', 'images': [{'url': 'https://i.scdn.co/image/full'}]}}}
        self.assertEqual(current_album(playing), Album('album1', 'https://i.scdn.co/image/full'))

class SignInTests(unittest.TestCase):
    def test_pkce_callback_is_validated_and_exchanged_before_credentials_are_saved(self):
        from unittest.mock import patch
        from urllib.parse import parse_qs, urlsplit
        from spotiframe.spotify import SpotifyClient
        with tempfile.TemporaryDirectory() as directory:
            store = TokenStore(Path(directory) / 'tokens.json')
            client = SpotifyClient('client', 'http://127.0.0.1:8888/callback', store)
            attempt = client.begin_authorization()
            query = parse_qs(urlsplit(attempt.url).query)
            self.assertEqual(query['state'], [attempt.state])
            with patch('spotiframe.spotify.request', return_value=(200, b'{"access_token":"access","refresh_token":"refresh","expires_in":3600}')) as token_request:
                with self.assertRaises(AuthenticationError):
                    client.complete_authorization('http://127.0.0.1:8888/callback?code=abc&state=wrong', attempt)
                self.assertFalse(store.path.exists())
                client.complete_authorization('http://127.0.0.1:8888/callback?code=abc&state=' + attempt.state, attempt)
                payload = parse_qs(token_request.call_args.kwargs['data'].decode())
                self.assertEqual(payload['code'], ['abc'])
                self.assertEqual(payload['code_verifier'], [attempt.verifier])
                self.assertEqual(store.load()['refresh_token'], 'refresh')

class HttpsRedirectTests(unittest.TestCase):
    def test_public_https_redirect_is_used_for_pkce(self):
        url, _, _ = authorization_request('client', 'https://frame.example.com/callback')
        self.assertEqual(parse_qs(urlsplit(url).query)['redirect_uri'], ['https://frame.example.com/callback'])

    def test_nonloopback_http_redirect_is_rejected(self):
        with self.assertRaises(ValueError):
            authorization_request('client', 'http://192.168.1.20:8888/callback')
