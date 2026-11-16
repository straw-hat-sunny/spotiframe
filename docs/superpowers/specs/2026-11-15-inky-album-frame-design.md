# Inky album frame v1

A Raspberry Pi Zero 2 W displays the cover of the currently playing Spotify track, while playback takes place on another device. Use Python and Pimoroni's Inky library, detecting the attached panel automatically. Poll the current-track Web API and update the e-paper only when the album changes; show a neutral screen when there is no supported playing track. Fit and center the complete artwork over a blurred background derived from the cover. Do not persist Spotify content.

Use Authorization Code with PKCE and only `user-read-currently-playing`. A headless user authorizes in a browser and pastes the loopback callback URL into the terminal; store refresh credentials in a user-only file, refresh access tokens, and prompt for authorization again after revocation or expiry. Respect 429 Retry-After and exponential backoff, and surface Spotify errors. Support a local preview without connected hardware.

Alternatives considered: (1) Web API polling, which follows playback on other devices and supports the requested setup; (2) Spotify Soloist events, which require playback through the Pi and therefore do not meet this setup. Python with the Web API is the chosen default.
