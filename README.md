# SpotiFrame

The picture frame that displays the currently playing Spotify album artwork.

## Local development on macOS

Copy `.env_example` to `.env`, add your Spotify credentials, and register this
exact redirect URI in the Spotify developer dashboard:

```text
http://127.0.0.1:8080/callback
```

Then run:

```sh
go run .
```

Open <http://127.0.0.1:8080> in a browser on the Mac. The loopback URL is the
default, so `PUBLIC_BASE_URL` can be omitted for this workflow.

## Test from a phone using the Mac

The phone and Mac must be on the same Wi-Fi network. Give the Mac a development
mDNS name so it cannot conflict with a Raspberry Pi using `spotiframe.local`:

```sh
sudo scutil --set LocalHostName spotiframe-dev
```

Install [Caddy](https://caddyserver.com/docs/install), set this in `.env`, and
register the exact redirect URI in Spotify's dashboard:

```dotenv
PUBLIC_BASE_URL=https://spotiframe-dev.local
```

```text
https://spotiframe-dev.local/callback
```

Run the application and Caddy from separate terminals:

```sh
go run .
caddy run --config Caddyfile
```

Install and trust Caddy's local root CA certificate on the phone before opening
<https://spotiframe-dev.local>. Run `caddy trust` to trust it on the Mac. The
certificate path is printed by Caddy when it first creates its local authority.

## Raspberry Pi setup

Set the Pi's operating-system hostname and enable Avahi. Avahi publishes the
hostname as `spotiframe.local`; the Go DNS-SD service registration is not needed
for a URL typed into a browser.

```sh
sudo hostnamectl set-hostname spotiframe
sudo apt-get install avahi-daemon
sudo systemctl enable --now avahi-daemon
sudo reboot
```

After reboot, verify `ping spotiframe.local` from another computer on the same
network. Guest Wi-Fi, client isolation, VPNs, and some firewall configurations
can block mDNS traffic on UDP port 5353.

On the Pi, install Caddy, copy this repository's `Caddyfile` into Caddy's
configuration location, and configure:

```dotenv
PUBLIC_BASE_URL=https://spotiframe.local
```

Register this exact Spotify redirect URI:

```text
https://spotiframe.local/callback
```

Restart the application and Caddy, install and trust Caddy's local root CA on
the phone, then open <https://spotiframe.local>. Caddy terminates HTTPS and
proxies requests to the Go server bound to `127.0.0.1:8080`.

When Caddy runs as a Linux system service, its local root certificate is
typically stored at:

```text
/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
```

Spotify requires the configured redirect URI to match exactly. If Spotify's
dashboard rejects the `.local` HTTPS URI, use a stable public HTTPS hostname or
tunnel instead; `http://spotiframe.local` is not an accepted fallback.
