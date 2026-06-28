# Container Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run SpotiFrame and Caddy consistently on macOS and Raspberry Pi with Docker Compose while keeping the service LAN-only.

**Architecture:** Compose runs the Go application on a private container network and exposes only Caddy on ports 80 and 443. The host continues to provide `spotiframe.local` or `spotiframe-dev.local` through Avahi/Bonjour. Named volumes persist the Spotify token and Caddy CA across restarts.

**Tech Stack:** Go 1.26.4, Docker multi-stage builds, Docker Compose, Caddy 2

---

### Task 1: Container-aware listen address

**Files:**
- Modify: `main.go`
- Modify: `main_test.go`

- [x] Add a failing test proving `LISTEN_ADDR` overrides the loopback default with `0.0.0.0:8080`.
- [x] Run `go test ./...` and confirm the test fails because `appConfig` has no listen-address configuration.
- [x] Add `ListenAddr` to `appConfig`, default it to `127.0.0.1:8080`, read `LISTEN_ADDR`, and pass the result to `http.Server`.
- [x] Run `go test ./...` and confirm all tests pass.

### Task 2: Docker and Compose runtime

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `compose.yaml`
- Modify: `Caddyfile`

- [x] Add a multi-stage Dockerfile that builds with Go 1.26.4 and runs as an unprivileged Alpine user with CA certificates and a writable `/data` directory.
- [x] Exclude secrets, tokens, Git metadata, and local build artifacts from the Docker build context.
- [x] Add an `app` service with `LISTEN_ADDR=0.0.0.0:8080`, no published ports, `.env` injection, and a persistent `/data` volume.
- [x] Add a `caddy` service that publishes 80/443, proxies to `app:8080`, and persists `/data` and `/config`.
- [x] Parameterize the Caddy upstream as `{$UPSTREAM:127.0.0.1:8080}` so direct and Compose workflows both work.
- [x] Run `docker compose config` and `docker compose build app`.

### Task 3: Deployment documentation and verification

**Files:**
- Modify: `.env_example`
- Modify: `README.md`

- [x] Document Docker as the primary Mac/phone and Raspberry Pi workflow, including hostname setup, environment configuration, startup, CA extraction, phone trust, health verification, logs, restart, and shutdown.
- [x] Preserve direct `go run .` instructions for Mac-only development.
- [x] Document that mDNS remains host-managed and the application is not exposed publicly.
- [x] Run `go test -count=1 ./...`, `go test -race -count=1 ./...`, `go vet ./...`, `go build`, `docker compose config`, and `docker compose build app`.
- [x] Commit and push the completed changes to `feature/mDNS-setup` so pull request #2 updates.
