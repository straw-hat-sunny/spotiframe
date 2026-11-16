"""Loopback-only live preview of the image sent to an Inky display."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import ipaddress
import json
import socket
from threading import Thread
from urllib.parse import urlsplit
import webbrowser

from .display import render_idle


PAGE = b'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpotiFrame preview</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: #161a18; color: #f2f5f1;
         font-family: -apple-system, BlinkMacSystemFont, sans-serif; display: grid; place-items: center; }
  main { width: min(880px, 100%); padding: 36px 24px; }
  header { display: flex; justify-content: space-between; align-items: baseline; gap: 20px; flex-wrap: wrap; }
  h1 { font-size: 22px; font-weight: 650; margin: 0 0 8px; letter-spacing: -.02em; }
  p { color: #a9b5ac; font-size: 14px; margin: 0; line-height: 1.5; }
  .badge { color: #b1dfb9; font-size: 13px; white-space: nowrap; }
  .signin { display: none; margin-top: 16px; padding: 10px 16px; background: #1ed760;
            color: #102016; font-weight: 600; border-radius: 8px; text-decoration: none; width: fit-content; }
  .screen { margin-top: 24px; background: white; line-height: 0; max-width: 800px;
            box-shadow: 0 12px 50px #0006; border-radius: 2px; overflow: hidden; }
  img { display: block; width: 100%; height: auto; }
  footer { padding-top: 20px; }
</style>
</head>
<body>
<main>
  <header><div><h1>SpotiFrame preview</h1><p>Inky Impression 7.3&quot; &middot; 800 &times; 480 pixels</p></div>
    <span class="badge">&#9679; LIVE PREVIEW</span></header>
  <div class="screen"><img id="frame" src="/frame.png" width="800" height="480" alt="Current display frame"></div>
  <a id="signin" class="signin" target="_blank" rel="noopener noreferrer">Sign in on this computer</a>
  <footer><p>Updates when the album changes. E-ink colors and refresh time may differ from this preview.</p></footer>
</main>
<script>
  const frame = document.getElementById('frame');
  setInterval(() => { frame.src = '/frame.png?t=' + Date.now(); }, 1500);
  async function updateSignin() {
    try {
      const response = await fetch('/status', {cache: 'no-store'});
      const data = await response.json();
      const link = document.getElementById('signin');
      if (data.authorization_url) { link.href = data.authorization_url; link.style.display = 'block'; }
      else { link.style.display = 'none'; link.removeAttribute('href'); }
    } catch (_) {}
  }
  updateSignin();
  setInterval(updateSignin, 1500);
</script>
</body>
</html>'''


def local_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(('8.8.8.8', 80))
        return sock.getsockname()[0]


class BrowserOutput:
    resolution = (800, 480)

    def __init__(self, open_browser=True, lan=False, lan_host=None):
        self._frame = b''
        self._signin = None
        self._lan = lan
        self._lan_host = lan_host or (local_ip() if lan else None)
        if self._lan_host:
            address = ipaddress.ip_address(self._lan_host)
            if address.version != 4 or address.is_unspecified or address.is_multicast:
                raise ValueError('The LAN host must be this computer’s reachable IPv4 address, not 0.0.0.0.')
        self.show(render_idle(self.resolution))
        output = self

        class Handler(BaseHTTPRequestHandler):
            def send_content(self, content, mime, status=200):
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Cache-Control', 'no-store, max-age=0')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                self.wfile.write(content)

            def valid_host(self):
                port = output._server.server_port
                allowed = {f'127.0.0.1:{port}'}
                if output._lan_host:
                    allowed.add(f'{output._lan_host}:{port}')
                return self.headers.get('Host') in allowed

            def do_GET(self):
                if not self.valid_host():
                    self.send_error(400)
                    return
                path = urlsplit(self.path).path
                if path == '/':
                    content, mime = PAGE, 'text/html; charset=utf-8'
                elif path == '/frame.png':
                    content, mime = output._frame, 'image/png'
                elif path == '/status':
                    signin = output._signin
                    auth = signin if signin and self.client_address[0] == '127.0.0.1' else None
                    content, mime = json.dumps({'authorization_url': auth}).encode(), 'application/json'
                else:
                    self.send_error(404)
                    return
                self.send_content(content, mime)

            def log_message(self, format, *args):
                pass

        self._server = ThreadingHTTPServer(('0.0.0.0' if lan else '127.0.0.1', 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.url = f'http://127.0.0.1:{self._server.server_port}/'
        print(f'Browser preview: {self.url}', flush=True)
        if self._lan:
            print(f'LAN preview: http://{self._lan_host}:{self._server.server_port}/', flush=True)
        if open_browser:
            webbrowser.open(self.url)

    def begin_signin(self, auth_url, receiver):
        self._signin = auth_url
        return auth_url

    def end_signin(self):
        self._signin = None

    def show(self, image):
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        self._frame = buffer.getvalue()

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        self._frame = b''
