import io
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from PIL import Image
from spotiframe.browser_preview import BrowserOutput


class BrowserPreviewTests(unittest.TestCase):
    def test_browser_serves_the_live_display_frame_without_caching(self):
        preview = BrowserOutput(open_browser=False)
        self.addCleanup(preview.close)
        self.assertTrue(preview.url.startswith('http://127.0.0.1:'))
        preview.show(Image.new('RGB', (800, 480), 'red'))
        with urlopen(preview.url + 'frame.png') as response:
            self.assertEqual(response.headers.get_content_type(), 'image/png')
            self.assertIn('no-store', response.headers['Cache-Control'])
            with Image.open(io.BytesIO(response.read())) as frame:
                self.assertEqual(frame.size, (800, 480))
                self.assertEqual(frame.getpixel((100, 100)), (255, 0, 0))
        preview.show(Image.new('RGB', (800, 480), 'blue'))
        with urlopen(preview.url + 'frame.png') as response:
            with Image.open(io.BytesIO(response.read())) as frame:
                self.assertEqual(frame.getpixel((100, 100)), (0, 0, 255))

    def test_browser_page_displays_native_dimensions_and_unknown_paths_are_not_served(self):
        preview = BrowserOutput(open_browser=False)
        self.addCleanup(preview.close)
        with urlopen(preview.url) as response:
            html = response.read().decode()
        self.assertIn('800', html)
        self.assertIn('480', html)
        self.assertIn('frame.png', html)
        with self.assertRaises(HTTPError) as error:
            urlopen(preview.url + '.env')
        self.assertEqual(error.exception.code, 404)
        error.exception.close()


if __name__ == '__main__':
    unittest.main()

class PairingTests(unittest.TestCase):
    def test_lan_preview_cannot_receive_a_callback_over_http(self):
        from urllib.request import Request
        class Receiver:
            def submit(self, value):
                raise AssertionError('LAN HTTP must not receive callbacks')
        preview = BrowserOutput(open_browser=False, lan=True, lan_host='127.0.0.1')
        self.addCleanup(preview.close)
        url = 'https://accounts.spotify.com/authorize?state=expected'
        self.assertEqual(preview.begin_signin(url, Receiver()), url)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(preview.url + 'callback', data=b'example=not-a-code'))
        self.assertEqual(error.exception.code, 501)
        error.exception.close()

    def test_https_redirect_uses_spotify_link_for_automatic_phone_return(self):
        preview = BrowserOutput(open_browser=False, lan=True, lan_host='127.0.0.1')
        self.addCleanup(preview.close)
        class Receiver:
            requires_https = True
        url = 'https://accounts.spotify.com/authorize?state=expected'
        self.assertEqual(preview.begin_signin(url, Receiver()), url)
