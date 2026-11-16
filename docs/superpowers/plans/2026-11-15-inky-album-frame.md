# Inky album frame Implementation Plan

> Implement locally using the existing Codex session. Exercise authentication, API errors, and display transitions with tests before implementation.

**Goal:** Show the current Spotify album on an Inky Impression attached to a Pi Zero 2 W.

**Architecture:** A PKCE credential store and Web API client supply album data to a polling loop. A renderer uses Pillow and either previews the image or sends it to the detected Inky display.

**Tech Stack:** Python 3, Pillow, Pimoroni Inky; Python unittest.

**Spec:** docs/superpowers/specs/2026-11-15-inky-album-frame-design.md

## Tasks

- [x] Implement PKCE, callback validation, secure credential storage, refresh and API error/backoff handling; verify with unit tests and a local HTTP server.
- [x] Implement current-album extraction, rendering, and display transition handling; test idle and unchanged-album cases and verify local preview.
- [x] Document Pi installation, Spotify app setup, authorization, service operation, and hardware verification.
