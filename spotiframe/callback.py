"""Receive Spotify's OAuth redirect on this machine's loopback interface."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Full, Queue
import secrets
from threading import Thread
from urllib.parse import parse_qs, urlsplit


class CallbackReceiver:
    def __init__(self, redirect_uri, state, listen_port=8888):
        parts = urlsplit(redirect_uri)
        valid_origin = (parts.scheme == 'https' and parts.hostname) or (parts.scheme == 'http' and parts.hostname == '127.0.0.1' and parts.port)
        if not (valid_origin and parts.path and not parts.username and not parts.password and not parts.query and not parts.fragment):
            raise ValueError('The callback must use HTTPS or http://127.0.0.1 with a port.')
        self.requires_https = parts.scheme == 'https'
        port = listen_port if self.requires_https else parts.port
        self._queue = Queue(maxsize=1)
        self._redirect_uri = redirect_uri
        self._state = state
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                request = urlsplit(self.path)
                if request.path != parts.path:
                    self.send_error(404)
                    return
                callback = redirect_uri + '?' + request.query
                try:
                    receiver.submit(callback)
                except ValueError:
                    self.send_error(400, 'Invalid authorization response')
                    return
                except Full:
                    self.send_error(409, 'Authorization response already received')
                    return
                body = (b'<!doctype html><title>SpotiFrame</title><p>Authorization received. You can return to SpotiFrame.</p>'
                        b'<script>history.replaceState(null, "", location.pathname)</script>')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self._server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def submit(self, callback):
        actual = urlsplit(callback)
        expected = urlsplit(self._redirect_uri)
        query = parse_qs(actual.query)
        received = query.get('state', [])
        if ((actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path)
                or len(received) != 1 or not secrets.compare_digest(received[0], self._state)
                or not (query.get('code') or query.get('error'))):
            raise ValueError('Invalid authorization response')
        self._queue.put_nowait(callback)

    def get(self, timeout=None):
        return self._queue.get(timeout=timeout)

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
