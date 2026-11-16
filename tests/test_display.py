import io
import tempfile
from pathlib import Path
import unittest
from PIL import Image
from spotiframe.display import FrameController, PreviewOutput, render_album, render_idle
from spotiframe.spotify import Album


class Recorder:
    def __init__(self):
        self.images = []
    def show(self, image):
        self.images.append(image.copy())


class DisplayTests(unittest.TestCase):
    def test_artwork_fits_display_without_cropping(self):
        cover = Image.new('RGB', (400, 400), 'red')
        cover.paste('green', (0, 80, 400, 320))
        cover.paste('blue', (0, 320, 400, 400))
        image = render_album(cover, (800, 480))
        self.assertEqual(image.size, (800, 480))
        self.assertEqual(image.getpixel((400, 30)), (255, 0, 0))
        self.assertEqual(image.getpixel((400, 240)), (0, 128, 0))
        self.assertEqual(image.getpixel((400, 450)), (0, 0, 255))
        self.assertNotEqual(image.getpixel((30, 240)), (0, 0, 0))
        self.assertNotEqual(image.getpixel((770, 240)), (0, 0, 0))

    def test_only_changes_album_or_transitions_to_idle(self):
        output = Recorder()
        downloads = []
        def download(url):
            downloads.append(url)
            return Image.new('RGB', (100, 100), 'red')
        controller = FrameController(output, download, (800, 480))
        album = Album('1', 'https://image/1')
        controller.update(album)
        controller.update(album)
        self.assertEqual(len(output.images), 1)
        self.assertEqual(downloads, ['https://image/1'])
        controller.update(None)
        controller.update(None)
        self.assertEqual(len(output.images), 2)
        controller.update(album)
        self.assertEqual(len(output.images), 3)

    def test_preview_refuses_to_overwrite_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview.png'
            path.write_text('keep')
            with self.assertRaises(FileExistsError):
                PreviewOutput(path)
            self.assertEqual(path.read_text(), 'keep')

    def test_idle_screen_is_solid_black(self):
        image = render_idle((800, 480))
        self.assertEqual(image.getextrema(), ((0, 0), (0, 0), (0, 0)))


if __name__ == '__main__':
    unittest.main()

class ArtworkLayoutTests(unittest.TestCase):
    def test_square_album_art_is_large_and_centered_on_the_display(self):
        cover = Image.new('RGB', (400, 400), 'red')
        image = render_album(cover, (800, 480))
        self.assertEqual(image.getpixel((180, 240)), (255, 0, 0))
        self.assertEqual(image.getpixel((620, 240)), (255, 0, 0))
        self.assertEqual(image.getpixel((400, 15)), (255, 0, 0))
        self.assertEqual(image.getpixel((400, 465)), (255, 0, 0))

class ArtOnlyTests(unittest.TestCase):
    def test_square_cover_uses_the_full_screen_height(self):
        cover = Image.new('RGB', (400, 400), 'red')
        frame = render_album(cover, (800, 480))
        self.assertEqual(frame.getpixel((400, 0)), (255, 0, 0))
        self.assertEqual(frame.getpixel((400, 479)), (255, 0, 0))
        self.assertEqual(frame.getpixel((700, 330)), (255, 0, 0))
        self.assertEqual(frame.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(frame.getpixel((799, 479)), (255, 0, 0))

    def test_background_is_blurred_while_the_cover_remains_sharp(self):
        cover = Image.new('RGB', (400, 400), 'black')
        cover.paste('white', (80, 0, 400, 400))
        frame = render_album(cover, (800, 480))
        self.assertTrue(0 < frame.getpixel((150, 240))[0] < 255)
        self.assertEqual(frame.getpixel((200, 240)), (0, 0, 0))
        self.assertEqual(frame.getpixel((400, 240)), (255, 255, 255))

class SignInDisplayTests(unittest.TestCase):
    def test_sign_in_frame_has_a_visible_qr_code_on_the_display(self):
        from spotiframe.display import render_signin
        frame = render_signin('https://accounts.spotify.com/authorize?state=sample', (800, 480))
        self.assertEqual(frame.size, (800, 480))
        self.assertEqual(frame.getpixel((0, 0)), (0, 0, 0))
        self.assertGreater(frame.crop((20, 40, 400, 440)).convert('L').histogram()[255], 10000)

class SignInTransitionTests(unittest.TestCase):
    def test_sign_in_screen_is_replaced_by_black_idle_after_authentication(self):
        output = Recorder()
        controller = FrameController(output, resolution=(800, 480))
        controller.show_signin('https://example.test/signin')
        self.assertNotEqual(output.images[-1].getextrema(), ((0, 0), (0, 0), (0, 0)))
        controller.update(None)
        self.assertEqual(output.images[-1].getextrema(), ((0, 0), (0, 0), (0, 0)))
