import os
import subprocess
import sys
import unittest


class CommandLineTests(unittest.TestCase):
    def test_missing_client_id_explains_how_to_configure(self):
        import tempfile
        from pathlib import Path
        env = os.environ.copy()
        env.pop('SPOTIFY_CLIENT_ID', None)
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-m', 'spotiframe', 'login'], cwd=directory, capture_output=True, text=True, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SPOTIFY_CLIENT_ID', result.stderr)

    def test_help_can_run_without_hardware_or_credentials(self):
        result = subprocess.run([sys.executable, '-m', 'spotiframe', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('login', result.stdout)


if __name__ == '__main__':
    unittest.main()

class ServiceTests(unittest.TestCase):
    def test_noninteractive_expired_authorization_starts_sign_in(self):
        from unittest.mock import patch
        from spotiframe import __main__ as cli
        from spotiframe.spotify import AuthenticationError
        class Client:
            def __init__(self, *args):
                pass
            def playing_album(self):
                raise AuthenticationError('Refresh token expired')
        class Display:
            resolution = (800, 480)
            def show(self, image):
                pass
        calls = []
        def start_signin(client, controller, pairing=None):
            calls.append(True)
            raise KeyboardInterrupt
        with patch.dict(os.environ, {'SPOTIFY_CLIENT_ID': 'client'}), \
             patch.object(sys, 'argv', ['spotiframe', 'run']), \
             patch.object(cli, 'SpotifyClient', Client), \
             patch('spotiframe.display.InkyOutput', Display), \
             patch.object(cli, 'sign_in', start_signin), \
             patch.object(sys.stdin, 'isatty', return_value=False):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(calls, [True])

class DotenvTests(unittest.TestCase):
    def test_client_id_can_be_read_from_dotenv_in_working_directory(self):
        import tempfile
        from pathlib import Path
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, '.env').write_text('SPOTIFY_CLIENT_ID=from-dotenv\n')
            env = os.environ.copy()
            env.pop('SPOTIFY_CLIENT_ID', None)
            env['PYTHONPATH'] = str(project)
            result = subprocess.run([sys.executable, '-m', 'spotiframe', 'run', '--interval', '1'], cwd=directory, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('polling interval', result.stderr)
            self.assertNotIn('Set SPOTIFY_CLIENT_ID', result.stderr)

    def test_environment_values_take_precedence_over_dotenv(self):
        import tempfile
        from pathlib import Path
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, '.env').write_text('SPOTIFY_CLIENT_ID=from-dotenv\n')
            env = os.environ.copy()
            env['SPOTIFY_CLIENT_ID'] = 'from-environment'
            env['SPOTIFY_REDIRECT_URI'] = 'http://127.0.0.1:8888/callback'
            env['PYTHONPATH'] = str(project)
            result = subprocess.run([sys.executable, '-m', 'spotiframe', 'login'], cwd=directory, env=env, input='', capture_output=True, text=True)
            self.assertIn('client_id=from-environment', result.stdout)
            self.assertNotIn('client_id=from-dotenv', result.stdout)

class BrowserCommandTests(unittest.TestCase):
    def test_browser_mode_does_not_use_inky_and_closes_server_when_stopped(self):
        from unittest.mock import patch
        from spotiframe import __main__ as cli
        from spotiframe.spotify import AuthenticationError
        instances = []
        class Client:
            def __init__(self, *args):
                pass
            def playing_album(self):
                raise AuthenticationError('Refresh token expired')
        class Browser:
            resolution = (800, 480)
            def __init__(self):
                self.closed = False
                instances.append(self)
            def show(self, image):
                pass
            def close(self):
                self.closed = True
        def start_signin(client, controller, pairing=None):
            raise KeyboardInterrupt
        with patch.dict(os.environ, {'SPOTIFY_CLIENT_ID': 'client'}), \
             patch.object(sys, 'argv', ['spotiframe', 'run', '--browser']), \
             patch.object(cli, 'SpotifyClient', Client), \
             patch('spotiframe.browser_preview.BrowserOutput', Browser), \
             patch.object(cli, 'sign_in', start_signin), \
             patch.object(sys.stdin, 'isatty', return_value=False):
            self.assertEqual(cli.main(), 0)
        self.assertTrue(instances[0].closed)

    def test_browser_and_file_preview_cannot_be_selected_together(self):
        result = subprocess.run([sys.executable, '-m', 'spotiframe', 'run', '--browser', '--preview', 'frame.png'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not allowed with argument', result.stderr)

class OrchestrationTests(unittest.TestCase):
    def test_run_switches_from_signin_to_black_when_nothing_is_playing(self):
        from unittest.mock import patch
        from spotiframe import __main__ as cli
        from spotiframe.spotify import AuthenticationError
        instances = []
        class Client:
            def __init__(self, *args):
                self.connected = False
            def playing_album(self):
                if not self.connected:
                    raise AuthenticationError('No credentials')
                return None
        class Browser:
            resolution = (800, 480)
            def __init__(self):
                self.images = []
                instances.append(self)
            def show(self, image):
                self.images.append(image.copy())
            def close(self):
                pass
        def connect(client, controller, pairing=None):
            controller.show_signin('https://example.test/authorize')
            client.connected = True
        with patch.dict(os.environ, {'SPOTIFY_CLIENT_ID': 'client'}), \
             patch.object(sys, 'argv', ['spotiframe', 'run', '--browser']), \
             patch.object(cli, 'SpotifyClient', Client), \
             patch('spotiframe.browser_preview.BrowserOutput', Browser), \
             patch.object(cli, 'sign_in', connect), \
             patch.object(cli.time, 'sleep', side_effect=KeyboardInterrupt):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(len(instances[0].images), 2)
        self.assertNotEqual(instances[0].images[0].getextrema(), ((0, 0), (0, 0), (0, 0)))
        self.assertEqual(instances[0].images[1].getextrema(), ((0, 0), (0, 0), (0, 0)))

class ReauthorizeTests(unittest.TestCase):
    def test_reauthorize_shows_sign_in_even_with_valid_credentials(self):
        from unittest.mock import patch
        from spotiframe import __main__ as cli
        calls = []
        class Client:
            def __init__(self, *args):
                pass
            def playing_album(self):
                return None
        class Browser:
            resolution = (800, 480)
            def show(self, image):
                pass
            def close(self):
                pass
        def connect(client, controller, pairing=None):
            calls.append('connected')
        with patch.dict(os.environ, {'SPOTIFY_CLIENT_ID': 'client'}), \
             patch.object(sys, 'argv', ['spotiframe', 'run', '--browser', '--reauthorize']), \
             patch.object(cli, 'SpotifyClient', Client), \
             patch('spotiframe.browser_preview.BrowserOutput', Browser), \
             patch.object(cli, 'sign_in', connect), \
             patch.object(cli.time, 'sleep', side_effect=KeyboardInterrupt):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(calls, ['connected'])
