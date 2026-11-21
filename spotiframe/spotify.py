"""Spotify PKCE authorization and currently-playing API client."""
from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
PLAYING_URL = 'https://api.spotify.com/v1/me/player/currently-playing'


class SpotifyError(Exception):
    pass


class AuthenticationError(SpotifyError):
    pass


@dataclass(frozen=True)
class Album:
    id: str
    image_url: str


@dataclass(frozen=True)
class AuthorizationAttempt:
    url: str
    verifier: str
    state: str


def authorization_request(client_id, redirect_uri):
    uri = urlsplit(redirect_uri)
    valid_origin = (uri.scheme == 'https' and uri.hostname) or (uri.scheme == 'http' and uri.hostname == '127.0.0.1' and uri.port)
    if not (valid_origin and uri.path and not uri.username and not uri.password and not uri.query and not uri.fragment):
        raise ValueError('Redirect URI must use HTTPS, or http://127.0.0.1 with a port and path')
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
    state = secrets.token_urlsafe(32)
    query = urlencode({'client_id': client_id, 'response_type': 'code', 'redirect_uri': redirect_uri, 'code_challenge_method': 'S256', 'code_challenge': challenge, 'state': state, 'scope': 'user-read-currently-playing'})
    return f'{AUTH_URL}?{query}', verifier, state


def callback_code(callback, state, redirect_uri):
    actual, expected = urlsplit(callback), urlsplit(redirect_uri)
    if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path):
        raise AuthenticationError('The callback URL does not match the configured redirect URI.')
    query = parse_qs(actual.query)
    if query.get('state') != [state]:
        raise AuthenticationError('Spotify authorization state did not match. Try again.')
    if 'error' in query:
        raise AuthenticationError('Spotify authorization was declined: ' + query['error'][0])
    codes = query.get('code', [])
    if len(codes) != 1 or not codes[0]:
        raise AuthenticationError('The callback URL does not contain an authorization code.')
    return codes[0]


class TokenStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        except (ValueError, OSError) as exc:
            raise AuthenticationError(f'Unable to read credentials: {exc}') from exc

    def save(self, token):
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as file:
                json.dump(token, file)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise


def retry_delay(retry_after, attempt):
    try:
        server_delay = max(0, int(retry_after))
    except (ValueError, TypeError):
        server_delay = 0
    return max(server_delay, min(300, 2 ** min(attempt, 9)))


def request(url, data=None, headers=None):
    """Make one request, respecting Spotify's 429 retry window and backoff."""
    attempt = 0
    while True:
        try:
            req = Request(url, data=data, headers=headers or {})
            with urlopen(req, timeout=30) as response:
                return response.status, response.read()
        except HTTPError as exc:
            if exc.code == 429:
                delay = retry_delay(exc.headers.get('Retry-After'), attempt)
                exc.close()
                print(f'Spotify rate limit; retrying in {delay} seconds.', flush=True)
                time.sleep(delay)
                attempt += 1
                continue
            payload = exc.read()
            exc.close()
            error = None
            try:
                body = json.loads(payload)
                error = body.get('error', {})
                message = error.get('message', '') if isinstance(error, dict) else body.get('error_description', error)
            except (ValueError, AttributeError):
                message = payload.decode('utf-8', 'replace')[:300]
            if exc.code == 401 or (exc.code == 400 and message and ('refresh token' in str(message).lower() or error == 'invalid_grant')):
                raise AuthenticationError(f'Spotify authorization failed (HTTP {exc.code}): {message}') from exc
            raise SpotifyError(f'Spotify request failed (HTTP {exc.code}): {message or exc.reason}') from exc
        except URLError as exc:
            raise SpotifyError(f'Network error: {exc.reason}') from exc


def current_album(body):
    if not isinstance(body, dict) or body.get('currently_playing_type') != 'track':
        return None
    item = body.get('item') or {}
    if not isinstance(item, dict) or item.get('type') != 'track':
        return None
    album = item.get('album') or {}
    images = album.get('images') or []
    album_id = album.get('id')
    image_url = next((image.get('url') for image in images if isinstance(image, dict) and image.get('url')), None)
    if not all((album_id, image_url)):
        return None
    return Album(album_id, image_url)


class SpotifyClient:
    def __init__(self, client_id, redirect_uri, store):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.store = store
        self.token = store.load()

    def login(self):
        attempt = self.begin_authorization()
        print('\nOpen this URL on any device and sign in:\n\n' + attempt.url)
        print('\nAfter approval, the browser may report that it cannot connect. Copy its full address bar URL.')
        callback = input('Paste the complete redirect URL: ').strip()
        self.complete_authorization(callback, attempt)
        print('Spotify authorization saved securely.')

    def begin_authorization(self):
        return AuthorizationAttempt(*authorization_request(self.client_id, self.redirect_uri))

    def complete_authorization(self, callback, attempt):
        code = callback_code(callback, attempt.state, self.redirect_uri)
        data = {'client_id': self.client_id, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': self.redirect_uri, 'code_verifier': attempt.verifier}
        self._token_request(data)

    def _token_request(self, data):
        _, raw = request(TOKEN_URL, data=urlencode(data).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
        response = json.loads(raw)
        refresh = response.get('refresh_token') or (self.token or {}).get('refresh_token')
        if not response.get('access_token') or not refresh or not response.get('expires_in'):
            raise AuthenticationError('Spotify did not provide usable credentials. Run login again.')
        self.token = {'access_token': response['access_token'], 'refresh_token': refresh, 'expires_at': time.time() + response['expires_in']}
        self.store.save(self.token)

    def refresh(self):
        if not self.token or not self.token.get('refresh_token'):
            raise AuthenticationError('No Spotify authorization found.')
        self._token_request({'client_id': self.client_id, 'grant_type': 'refresh_token', 'refresh_token': self.token['refresh_token']})

    def playing_album(self):
        if not self.token or time.time() >= self.token.get('expires_at', 0) - 60:
            self.refresh()
        try:
            status, raw = request(PLAYING_URL, headers={'Authorization': 'Bearer ' + self.token['access_token']})
        except AuthenticationError:
            self.refresh()
            status, raw = request(PLAYING_URL, headers={'Authorization': 'Bearer ' + self.token['access_token']})
        if status == 204 or not raw:
            return None
        try:
            return current_album(json.loads(raw))
        except (ValueError, TypeError) as exc:
            raise SpotifyError('Spotify returned an invalid playback response.') from exc
