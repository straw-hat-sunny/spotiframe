# SpotiFrame

SpotiFrame displays the album art for the current Spotify track on a Pimoroni Inky Impression 7.3 connected to a Raspberry Pi Zero 2 W. You can also preview the 800 × 480 display in a browser on your Mac.

The full cover is centered over a blurred background. When playback pauses or nothing is playing, the frame keeps the last album artwork it displayed. Spotify is checked every 30 seconds by default, and the display refreshes only when the album changes. The Inky retains its image when the app stops; artwork is not saved to disk. If no artwork has been displayed yet, there may be no album to show until Spotify provides one.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.11 or newer.
- A [Spotify developer app](https://developer.spotify.com/dashboard) and its client ID. The app uses Authorization Code with PKCE, so it does **not** need your client secret. Spotify requires the app owner to have Premium for [development-mode apps](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).
- For automatic sign-in from a phone: [cloudflared](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/). A Quick Tunnel needs no account or domain.
- For the physical display: a Pi Zero 2 W with 64-bit Raspberry Pi OS Bookworm or newer, network access, and an Inky Impression 7.3. Configure I2C and SPI using [Pimoroni's setup guide](https://learn.pimoroni.com/article/getting-started-with-inky-impression).

## Set up the project

On your Mac, open a terminal in the project directory and install the locked dependencies:

```sh
cd /path/to/spotiframe
uv sync --locked
```

On the Pi, install the Inky driver as well:

```sh
cd /path/to/spotiframe
uv sync --locked --extra pi
```

The Pi may need the `build-essential` OS package to compile `spidev` if a wheel is unavailable. The project uses its own `.venv`, not the environment created by Pimoroni's installer.

If you don't already have a `.env` file, copy the example:

```sh
cp .env.example .env
```

Edit `.env` and set `SPOTIFY_CLIENT_ID` to the client ID from your Spotify app. Leave your client secret out of the file. The Quick Tunnel steps below will set `SPOTIFY_REDIRECT_URI`.

## Start a Cloudflare Quick Tunnel

Run the tunnel on the **same computer as SpotiFrame**: your Mac for the browser preview, or the Pi for the physical display. Cloudflare creates a public HTTPS URL that forwards to the local sign-in callback. Anyone with the URL can reach that callback while the tunnel runs; the app validates the authorization state and uses PKCE.

1. Install `cloudflared`. On a Mac with Homebrew:

   ```sh
   brew install cloudflared
   ```

   On Raspberry Pi OS, follow Cloudflare's [Linux installation instructions](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/) for ARM64.

2. In a terminal, start the tunnel and leave it running:

   ```sh
   cloudflared tunnel --url http://127.0.0.1:8888
   ```

   Copy the `https://...trycloudflare.com` URL printed by Cloudflare and append `/callback`. For example:

   ```text
   https://example-words.trycloudflare.com/callback
   ```

3. In your [Spotify developer dashboard](https://developer.spotify.com/dashboard), open your app's settings and add **that exact callback URL** to Redirect URIs. If a different Spotify account will sign in, add it to the app's user management settings.

4. Set the same URL in `.env`, replacing the example with your actual tunnel hostname:

   ```dotenv
   SPOTIFY_REDIRECT_URI=https://example-words.trycloudflare.com/callback
   ```

   Spotify requires an exact match, including `/callback`. The app listens for the callback on `127.0.0.1:8888` during sign-in; Cloudflare provides HTTPS between the phone and the tunnel.

A Quick Tunnel is temporary: its hostname changes when you start a new one. Each time that happens, update **both** the Spotify dashboard and `.env` before signing in again. See [Cloudflare's Quick Tunnel guide](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) for details.

## Run and sign in

Keep the tunnel running. In a **second terminal**, open the project directory and start the Mac preview:

```sh
uv run --locked python -m spotiframe run --browser
```

The preview opens automatically; if it doesn't, open the `http://127.0.0.1` address printed in the terminal. If sign-in is needed, it shows a QR code. Scan it on your phone and approve access in Spotify; the HTTPS redirect completes the sign-in and the artwork appears when music is playing.

To test the QR flow when you're already signed in, use:

```sh
uv run --locked python -m spotiframe run --browser --reauthorize
```

Existing credentials are replaced only after successful sign-in. For the physical Inky display, run this on the Pi instead:

```sh
uv run --locked --extra pi python -m spotiframe run
```

Use `--reauthorize` there too if you want to show the sign-in QR again. Press Ctrl+C in each terminal to stop the app and tunnel.

The app requests only `user-read-currently-playing`. Credentials are stored in `~/.local/state/spotiframe/tokens.json` (or `$XDG_STATE_HOME/spotiframe/tokens.json`) with directory mode `0700` and file mode `0600`. Access tokens refresh automatically. If Spotify expires or revokes the refresh token, SpotiFrame shows a new QR code; Spotify currently gives refresh tokens a [six-month lifetime](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens). A working tunnel and registered callback are needed when you sign in again, not for ordinary access-token refreshes.

## Troubleshooting

- **Invalid redirect URI:** Check that the tunnel is running and `SPOTIFY_REDIRECT_URI` in `.env` exactly matches the URL registered in Spotify, including `/callback`. A restarted Quick Tunnel has a new hostname. Environment variables already set in your shell take precedence over `.env`.
- **Tunnel returns 502:** The callback server listens on port 8888 only while the app is waiting for Spotify sign-in. Start the app with `--reauthorize`, then scan the QR code; opening the tunnel URL at other times can return 502.
- **Port 8888 is in use:** Stop the other process using that port. If you change the app's local callback port using `SPOTIFRAME_CALLBACK_PORT`, point the tunnel at that same port.
- **Black screen:** Start playing a Spotify track on one of your devices. The display needs an available album cover before it can show artwork.

For local Mac sign-in without a tunnel, register `http://127.0.0.1:8888/callback` in the dashboard and set it as `SPOTIFY_REDIRECT_URI` in `.env`. Run the browser preview and select **Sign in on this computer**. A phone cannot automatically return to the Mac through this loopback address.

## Preview options and tests

The browser preview shows the image sent to the Inky; e-ink colors and refresh time will differ. To save a temporary PNG instead, use `--preview /tmp/spotiframe-preview.png`. The file must not already exist and is removed on normal exit, Ctrl+C, or SIGTERM; remove it manually if the process is forcibly killed. Use `--interval 15` to change the Spotify polling interval (minimum 10 seconds).

Run the tests without a Spotify account or connected display:

```sh
uv run --locked python -m unittest discover -s tests -v
```

Some tests use a temporary loopback HTTP server and require permission to bind to `127.0.0.1`.

## Running the Pi at startup

After testing the display, create a systemd service as your Pi user. Replace the username and project directory with your values:

```ini
[Unit]
Description=Spotify album art on Inky Impression
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_PI_USERNAME
WorkingDirectory=/home/YOUR_PI_USERNAME/spotiframe
ExecStart=/home/YOUR_PI_USERNAME/spotiframe/.venv/bin/python -m spotiframe run
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Save it as `/etc/systemd/system/spotiframe.service`, then run `sudo systemctl daemon-reload`, `sudo systemctl enable --now spotiframe`, and `journalctl -u spotiframe -f`. The service runs as the user that owns the private tokens. A Quick Tunnel still needs to be started separately, with its current callback registered and configured, whenever sign-in is needed. For an unattended setup, use a stable HTTPS hostname and a TLS reverse proxy or tunnel that forwards `/callback` to `127.0.0.1:8888` on the Pi.

Spotify and its content are subject to [Spotify's developer terms](https://developer.spotify.com/terms) and [design guidelines](https://developer.spotify.com/documentation/design). This personal preview uses a blurred artwork background and omits attribution and a link back to Spotify; those choices conflict with the guidelines.
