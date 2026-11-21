"""Render one album without saving Spotify artwork to disk."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
import qrcode
from .spotify import SpotifyError, request


def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/System/Library/Fonts/Helvetica.ttc'):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_signin(url, resolution):
    width, height = resolution
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
    code.add_data(url)
    code.make(fit=True)
    modules = len(code.get_matrix())
    code.box_size = min(height - 40, width // 2 - 40) // modules
    if code.box_size < 2:
        raise ValueError('Sign-in QR code is too large for this display.')
    qr = code.make_image(fill_color='black', back_color='white').convert('RGB')
    image = Image.new('RGB', resolution, 'black')
    image.paste(qr, (20, (height - qr.height) // 2))
    draw = ImageDraw.Draw(image)
    x = width // 2 + 15
    draw.text((x, height // 2 - 50), 'Connect Spotify', font=font(30), fill='white')
    draw.text((x, height // 2 + 5), 'Scan the QR code', font=font(20), fill='white')
    draw.text((x, height // 2 + 38), 'to sign in.', font=font(20), fill='white')
    return image


def render_album(cover, resolution):
    width, height = resolution
    if width < 640 or height < 360:
        raise ValueError('Display must be at least 640 × 360 pixels.')
    source = cover.convert('RGB')
    artwork = ImageOps.contain(source, resolution, Image.Resampling.LANCZOS)
    frame = ImageOps.fit(source, resolution, Image.Resampling.LANCZOS)
    frame = frame.filter(ImageFilter.GaussianBlur(radius=max(1, min(width, height) // 16)))
    frame.paste(artwork, ((width - artwork.width) // 2, (height - artwork.height) // 2))
    return frame


def render_idle(resolution):
    return Image.new('RGB', resolution, 'black')


def download_cover(url):
    if not url.startswith('https://'):
        raise SpotifyError('Spotify returned an insecure artwork URL.')
    _, data = request(url)
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            return image.convert('RGB')
    except (OSError, ValueError) as exc:
        raise SpotifyError('Unable to decode the Spotify album artwork.') from exc


class FrameController:
    def __init__(self, output, download=download_cover, resolution=(800, 480)):
        self.output = output
        self.download = download
        self.resolution = resolution
        self.current = None
        self.last_image = None
        self.signin_visible = False

    def show_signin(self, url):
        self.output.show(render_signin(url, self.resolution))
        self.signin_visible = True

    def update(self, album):
        if album is None:
            if self.signin_visible:
                self.output.show(self.last_image if self.last_image is not None else render_idle(self.resolution))
                self.signin_visible = False
            return
        if album.id == self.current:
            if self.signin_visible:
                self.output.show(self.last_image)
                self.signin_visible = False
            return
        image = render_album(self.download(album.image_url), self.resolution)
        self.output.show(image)
        self.current = album.id
        self.last_image = image
        self.signin_visible = False


class InkyOutput:
    def __init__(self):
        from inky.auto import auto
        self.display = auto(ask_user=False, verbose=False)
        if self.display is None:
            raise RuntimeError('No Inky display detected. Check the connection, I2C and SPI.')
        self.resolution = tuple(self.display.resolution)

    def show(self, image):
        self.display.set_image(image)
        self.display.show()


class PreviewOutput:
    def __init__(self, path):
        self.path = Path(path)
        # Reserve our own file, so cleaning it up can never delete an existing file.
        with self.path.open('xb'):
            pass
        self.resolution = (800, 480)

    def show(self, image):
        image.save(self.path)
        print(f'Preview updated: {self.path}', flush=True)
