# SpotiFrame Producer Design

## Purpose

Build the first SpotiFrame component: a lightweight Go producer that runs as a Home Assistant add-on and publishes the current Spotify album artwork URL to MQTT. A separate Raspberry Pi consumer will subscribe later, download the artwork, and render it on a picture frame.

This design intentionally focuses on the producer. The consumer is represented only by the MQTT contract it will consume.

## Scope

In scope:

- Go daemon for Spotify authentication, polling, state comparison, and MQTT publishing.
- Home Assistant add-on packaging with `config.yaml`, `Dockerfile`, `run.sh`, user-facing docs, and options schema.
- One-time browser-based Spotify OAuth setup.
- Persistent Spotify refresh-token storage under `/data`.
- Single retained MQTT JSON topic.
- Progress-aware Spotify polling.
- Local development mode outside Home Assistant.

Out of scope:

- Raspberry Pi display consumer implementation.
- Downloading, resizing, caching, or publishing image bytes.
- Home Assistant discovery entities.
- Playback control or any Spotify write operations.

## Architecture

The producer is one Go binary with clear internal package boundaries:

- `config`: reads Home Assistant `/data/options.json` or a local config file, validates required settings, and normalizes defaults.
- `auth`: exposes the one-time OAuth browser flow, validates callback state, exchanges authorization codes, refreshes access tokens, and stores token data.
- `spotify`: wraps Spotify's currently-playing API and maps responses into internal playback snapshots.
- `scheduler`: chooses the next poll time using playback progress and fallback intervals.
- `publisher`: manages MQTT connection/reconnection and publishes retained JSON snapshots.
- `app`: wires configuration, auth server, poll loop, Spotify client, and MQTT publisher together.

The add-on exposes a small HTTP server with:

- `GET /login`: redirects the user to Spotify authorization.
- `GET /callback`: receives Spotify's OAuth callback, validates `state`, exchanges the code, and persists the token.
- `GET /healthz`: reports process health and authentication status.

The daemon starts the HTTP server at boot. If no Spotify token is stored, it remains running and logs that authentication is required. Once authenticated, it polls Spotify and publishes MQTT updates.

## Spotify Authentication

The producer uses Spotify Authorization Code Flow.

Configuration includes:

- Spotify client ID.
- Spotify client secret.
- Redirect URI registered in the Spotify developer dashboard.
- Local HTTP listen address and port.

The requested Spotify scope is:

- `user-read-currently-playing`

Token data is stored in `/data/spotiframe-token.json` for Home Assistant runtime persistence. The file contains refresh-token state and any access-token metadata needed by the Go OAuth client. Refresh is automatic during normal operation. If refresh fails permanently, the daemon logs that reauthentication is required and stops polling until the user completes `/login` again.

## Spotify Polling

The producer calls Spotify's currently-playing endpoint and converts the response into an internal snapshot.

Internal snapshot fields may include:

- Playback state.
- Item type.
- Track or episode ID.
- Album art URL.
- Duration.
- Progress.
- Observed time.

Only `is_playing` and `album_art_url` are published to MQTT. Other fields are used for scheduling and duplicate publish suppression.

When Spotify reports no active item, returns no content, or returns an item without artwork, the producer treats that as an idle display state.

## MQTT Contract

The producer publishes one retained JSON payload to a configurable topic. The default topic is:

```text
spotiframe/now_playing
```

Playing payload:

```json
{
  "schema_version": 1,
  "is_playing": true,
  "album_art_url": "https://i.scdn.co/image/..."
}
```

Idle payload:

```json
{
  "schema_version": 1,
  "is_playing": false,
  "album_art_url": null
}
```

Publish rules:

- Publish with retain enabled.
- Publish when `is_playing` changes.
- Publish when `album_art_url` changes.
- Do not publish only because track progress changed.
- Do not publish idle solely because Spotify or MQTT is temporarily unavailable.

This keeps the consumer simple: it only needs to parse the schema version, decide whether artwork should be shown, and download the supplied URL.

## Poll Scheduling

Polling is progress-aware.

While playing:

- Estimate the remaining time from Spotify `duration_ms - progress_ms`.
- Schedule the next poll near the expected track boundary.
- Clamp the delay between configurable minimum and maximum intervals so skips, seeks, pauses, and drift are still detected.

While idle or unauthenticated:

- Poll at a configurable idle interval after authentication.
- Do not poll Spotify before authentication.

After errors:

- Use exponential backoff with a maximum cap.
- Honor Spotify `Retry-After` when the API returns rate limiting.
- Resume normal scheduling after a successful poll.

Initial default values:

- Minimum poll interval: 5 seconds.
- Maximum playing poll interval: 30 seconds.
- Boundary lookahead: 2 seconds.
- Idle poll interval: 30 seconds.
- Maximum error backoff: 5 minutes.

These defaults are configurable through the add-on options schema.

## Error Handling

Configuration errors are fatal and should produce clear startup logs.

Spotify errors:

- `401`: try token refresh; if refresh fails, require reauthentication.
- `403`: log the authorization or account problem and back off.
- `429`: honor `Retry-After`.
- Network or temporary server errors: back off and retry.

MQTT errors:

- Initial connection failure retries with backoff.
- Disconnects trigger background reconnect.
- Publish failures are logged and retried on the next state change or reconnect.

Operational states are not conflated with playback states. Temporary API or broker failures do not cause the producer to publish `is_playing: false`.

## Home Assistant Add-on Packaging

The repository will include an add-on directory for the producer with:

- `config.yaml`
- `Dockerfile`
- `run.sh`
- `README.md`
- `DOCS.md`

The add-on config exposes:

- Spotify client ID.
- Spotify client secret.
- Spotify redirect URI.
- HTTP listen port.
- MQTT broker host.
- MQTT broker port.
- MQTT username.
- MQTT password.
- MQTT topic.
- Polling intervals.

The container stores runtime state in `/data`. It exposes one HTTP port for OAuth setup and health checks.

Supported architectures for the first add-on package:

- `aarch64`
- `amd64`

The Dockerfile should use an explicit Home Assistant base image rather than relying on an externally provided default base image.

## Local Development

The Go daemon can run outside Home Assistant by accepting a path to a local config file. Local mode should use the same core application code, token file format, OAuth callback server, Spotify polling logic, and MQTT publisher.

This keeps local development fast while preserving parity with the Home Assistant add-on runtime.

## Testing Strategy

Unit tests:

- Config loading and validation.
- MQTT payload construction.
- Duplicate publish detection.
- Poll scheduler timing decisions.
- Spotify response mapping for playing, idle, missing artwork, and unsupported item types.

Integration-style tests with fakes:

- OAuth callback state validation and token persistence.
- Spotify token refresh behavior.
- MQTT publisher behavior using a test broker or mocked client interface.

Manual verification:

- Run the Go app locally with a test config.
- Complete Spotify OAuth through `/login`.
- Publish retained payloads to a local MQTT broker.
- Confirm an MQTT subscriber receives only the minimal payload.
- Confirm Home Assistant add-on container starts, exposes `/healthz`, stores token data under `/data`, and reconnects after restart.

## Open Decisions Locked By This Design

- The first implementation is producer-first.
- The producer publishes album art URLs, not image bytes.
- MQTT uses one retained JSON topic.
- The public payload contains only `schema_version`, `is_playing`, and `album_art_url`.
- Nothing playing is represented by `is_playing: false` and `album_art_url: null`.
- Polling is progress-aware.
- Home Assistant add-on packaging is included in the first build.
