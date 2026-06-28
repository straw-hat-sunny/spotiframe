# SpotiFrame

SpotiFrame displays the album artwork for the currently playing Spotify track.
It runs locally on a Mac or Raspberry Pi and can be configured from a phone on
the same network.

```text
Phone -> https://spotiframe.local -> Caddy container -> Go container
```

The service is not exposed to the public internet. The browser and application
still require outbound internet access for Spotify authentication and API calls.

## Prerequisites

- A [Spotify developer application](https://developer.spotify.com/dashboard)
- Its client ID and client secret
- Docker with Docker Compose
- A phone and server on the same non-guest Wi-Fi network

Use [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/)
on macOS. On Raspberry Pi OS, install
[Docker Engine and the Compose plugin](https://docs.docker.com/engine/install/debian/).

Do not commit `.env`, `token.json`, or Caddy's root certificate. They contain
credentials or establish trust and are ignored by the Docker build where
appropriate.

## Quick Mac-only development

Use this workflow when the browser and Go server both run on the Mac. It does
not test phone access, mDNS, Docker, or Caddy.

1. Register this exact redirect URI in the Spotify developer dashboard:

   ```text
   http://127.0.0.1:8080/callback
   ```

2. Create `.env` and add the Spotify credentials:

   ```sh
   cp .env_example .env
   ```

   ```dotenv
   SPOTIFY_CLIENT_ID=your-client-id
   SPOTIFY_CLIENT_SECRET=your-client-secret
   PUBLIC_BASE_URL=http://127.0.0.1:8080
   ```

3. Start the application and open <http://127.0.0.1:8080>:

   ```sh
   go run .
   ```

The callback stores the Spotify token in `token.json` on the Mac.

## Test the containers from a phone using a Mac

### 1. Configure the local hostname

Give the Mac a development-only hostname so it cannot conflict with a Pi using
`spotiframe.local`:

```sh
sudo scutil --set LocalHostName spotiframe-dev
scutil --get LocalHostName
ping spotiframe-dev.local
```

Stop `ping` with `Ctrl+C` after the hostname resolves.

### 2. Configure Spotify and the environment

Register this exact redirect URI in the Spotify dashboard:

```text
https://spotiframe-dev.local/callback
```

Create `.env`:

```sh
cp .env_example .env
```

```dotenv
SPOTIFY_CLIENT_ID=your-client-id
SPOTIFY_CLIENT_SECRET=your-client-secret
PUBLIC_BASE_URL=https://spotiframe-dev.local
```

### 3. Start the containers

Start Docker Desktop, then run:

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Only Caddy publishes host ports. The Go server listens on `0.0.0.0:8080`
inside the private Compose network and is not published directly to the LAN.

View startup logs with:

```sh
docker compose logs -f app caddy
```

### 4. Install the local CA on the phone

Caddy creates and retains a local certificate authority in its persistent
volume. Copy its public root certificate from the container:

```sh
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./root.crt
```

Install `root.crt` on the phone; never copy or share `root.key`.

- On iOS, install the certificate profile, then enable it under **Settings >
  General > About > Certificate Trust Settings**.
- On Android, install it as a CA certificate under the device security or
  credential settings. The exact menu name varies by Android version.

Only trust a root certificate produced by your own Caddy container.

### 5. Verify the complete flow

On the phone:

1. Open <https://spotiframe-dev.local/healthz>. It should return JSON containing
   `"status":"ok"`.
2. Open <https://spotiframe-dev.local> and complete Spotify authorization.
3. Confirm the browser returns to `/callback` and then `/current-track`.

The Spotify token is stored in the persistent `spotiframe-data` Docker volume.

Stop the services without deleting their data:

```sh
docker compose down
```

Do not use `docker compose down -v` unless you intentionally want to delete the
Spotify token and Caddy CA. Deleting the CA requires reinstalling a new
certificate on every phone.

## Deploy the containers to Raspberry Pi

These steps assume Raspberry Pi OS with Docker Engine and the Docker Compose
plugin installed.

### 1. Configure host mDNS

Set the host name and enable Avahi on the Pi. mDNS stays on the host instead of
running inside Docker.

```sh
sudo hostnamectl set-hostname spotiframe
sudo apt-get update
sudo apt-get install avahi-daemon
sudo systemctl enable --now avahi-daemon
sudo reboot
```

After reboot, verify the name from another LAN device:

```sh
ping spotiframe.local
```

If it does not resolve, verify both devices are on the same Wi-Fi. Guest Wi-Fi,
client isolation, VPNs, and firewalls can block mDNS traffic on UDP port 5353.

### 2. Configure Spotify and SpotiFrame

Register this exact redirect URI in the Spotify dashboard:

```text
https://spotiframe.local/callback
```

Clone the repository, enter it, and create `.env`:

```sh
cp .env_example .env
```

```dotenv
SPOTIFY_CLIENT_ID=your-client-id
SPOTIFY_CLIENT_SECRET=your-client-secret
PUBLIC_BASE_URL=https://spotiframe.local
```

### 3. Build and start

Compose builds the Go image for the Pi's architecture automatically:

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Both services use `restart: unless-stopped`, so they restart after a reboot when
the Docker service starts.

Inspect logs when needed:

```sh
docker compose logs --tail=100 app caddy
```

### 4. Trust the Caddy CA and authorize Spotify

Copy the public CA certificate out of the Caddy container:

```sh
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./root.crt
```

Transfer `root.crt` locally to the phone and follow the trust instructions from
the Mac section. Then open these URLs in order:

1. <https://spotiframe.local/healthz>
2. <https://spotiframe.local>

Complete Spotify authorization. The callback stores the token in the named
volume and redirects to `/current-track`. If no song is playing,
`/current-track` can legitimately report “no track currently playing.”

## Container maintenance

```sh
# Status
docker compose ps

# Follow logs
docker compose logs -f app caddy

# Rebuild after pulling code changes
docker compose up -d --build

# Restart without rebuilding
docker compose restart

# Stop while preserving tokens and certificates
docker compose down
```

Persistent data:

- `spotiframe-data` stores `token.json`.
- `caddy-data` stores Caddy certificates and its local CA.
- `caddy-config` stores Caddy runtime configuration.

## Troubleshooting

- **`spotiframe.local` does not resolve:** verify Avahi with
  `systemctl status avahi-daemon` and disable VPNs while testing.
- **Connection refused:** run `docker compose ps` and inspect both service logs.
- **Certificate warning:** reinstall and fully trust the current Caddy
  `root.crt`. Confirm the `caddy-data` volume was not deleted.
- **Spotify reports a redirect mismatch:** the dashboard URI must exactly equal
  `PUBLIC_BASE_URL` plus `/callback`.
- **Port 80 or 443 is already allocated:** stop the existing web server or proxy
  using that port before starting Compose.
- **Spotify rejects the `.local` redirect URI:** Spotify does not permit an HTTP
  LAN callback. A stable public HTTPS callback would be required instead, which
  is outside this local-only design.
