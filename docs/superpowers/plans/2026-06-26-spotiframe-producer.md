# SpotiFrame Producer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Go Home Assistant add-on producer that authenticates with Spotify, polls the current playback state, and publishes a retained minimal album-art MQTT payload.

**Architecture:** One Go binary wires focused internal packages for config, OAuth/token storage, Spotify polling, scheduling, MQTT publishing, and application orchestration. The Home Assistant add-on wraps that binary with `config.yaml`, `Dockerfile`, `run.sh`, and docs while the same binary remains runnable locally with a JSON config file.

**Tech Stack:** Go 1.26 module, standard `net/http`, `golang.org/x/oauth2`, `github.com/eclipse/paho.mqtt.golang`, Home Assistant add-on/app packaging, JSON config and payloads.

---

## File Structure

Create or modify these files:

- Modify: `go.mod` - adopt the existing untracked module file and add runtime dependencies.
- Create: `cmd/spotiframe-producer/main.go` - CLI entrypoint, signal handling, config path selection, app startup.
- Create: `internal/config/config.go` - config types, defaults, JSON loading, validation, Home Assistant `/data/options.json` behavior.
- Create: `internal/config/config_test.go` - config defaulting and validation tests.
- Create: `internal/payload/payload.go` - public MQTT payload type and change detection.
- Create: `internal/payload/payload_test.go` - JSON shape and change detection tests.
- Create: `internal/scheduler/scheduler.go` - progress-aware and error-backoff polling decisions.
- Create: `internal/scheduler/scheduler_test.go` - scheduler boundary, clamp, idle, and backoff tests.
- Create: `internal/spotify/client.go` - Spotify currently-playing client, OAuth HTTP client use, and response mapping.
- Create: `internal/spotify/client_test.go` - fake HTTP tests for playing, idle, missing artwork, rate limit, and auth errors.
- Create: `internal/auth/store.go` - token file persistence under `/data`.
- Create: `internal/auth/server.go` - `/login`, `/callback`, and `/healthz` HTTP handlers.
- Create: `internal/auth/store_test.go` - token store read/write and missing-file behavior.
- Create: `internal/auth/server_test.go` - state validation and health response tests.
- Create: `internal/mqtt/publisher.go` - MQTT client wrapper, retained publish, reconnect options.
- Create: `internal/mqtt/publisher_test.go` - publisher tests using a fake adapter.
- Create: `internal/app/app.go` - app orchestration loop with interfaces for Spotify, scheduler, auth, and MQTT.
- Create: `internal/app/app_test.go` - verifies publish-on-change and no idle publish on transient errors.
- Create: `addons/spotiframe-producer/config.yaml` - Home Assistant add-on metadata, options, schema, ports, arch.
- Create: `addons/spotiframe-producer/Dockerfile` - multi-stage Go build and explicit Home Assistant base image.
- Create: `addons/spotiframe-producer/run.sh` - starts the binary with `/data/options.json`.
- Create: `addons/spotiframe-producer/README.md` - short add-on overview.
- Create: `addons/spotiframe-producer/DOCS.md` - setup, Spotify redirect URI, MQTT payload, troubleshooting.
- Modify: `README.md` - document repo layout and producer-first scope.

## Task 1: Adopt Module And Add Config Loading

**Files:**
- Modify: `go.mod`
- Create: `internal/config/config.go`
- Create: `internal/config/config_test.go`

- [ ] **Step 1: Write failing config tests**

Create `internal/config/config_test.go`:

```go
package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoadAppliesDefaults(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "options.json")
	err := os.WriteFile(path, []byte(`{
		"spotify_client_id": "client-id",
		"spotify_client_secret": "client-secret",
		"spotify_redirect_uri": "http://localhost:8099/callback",
		"mqtt_host": "mqtt.local"
	}`), 0o600)
	if err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if cfg.HTTP.ListenAddr != ":8099" {
		t.Fatalf("ListenAddr = %q, want :8099", cfg.HTTP.ListenAddr)
	}
	if cfg.MQTT.Port != 1883 {
		t.Fatalf("MQTT.Port = %d, want 1883", cfg.MQTT.Port)
	}
	if cfg.MQTT.Topic != "spotiframe/now_playing" {
		t.Fatalf("MQTT.Topic = %q", cfg.MQTT.Topic)
	}
	if cfg.Paths.TokenFile != "/data/spotiframe-token.json" {
		t.Fatalf("TokenFile = %q", cfg.Paths.TokenFile)
	}
	if cfg.Polling.MinInterval != 5*time.Second {
		t.Fatalf("MinInterval = %s", cfg.Polling.MinInterval)
	}
}

func TestLoadRejectsMissingRequiredFields(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "options.json")
	if err := os.WriteFile(path, []byte(`{"mqtt_host":"mqtt.local"}`), 0o600); err != nil {
		t.Fatal(err)
	}

	_, err := Load(path)
	if err == nil {
		t.Fatal("Load returned nil error")
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/config
```

Expected: FAIL because package `internal/config` and `Load` do not exist.

- [ ] **Step 3: Implement config loading**

Create `internal/config/config.go`:

```go
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"time"
)

type Config struct {
	Spotify SpotifyConfig
	HTTP    HTTPConfig
	MQTT    MQTTConfig
	Polling PollingConfig
	Paths   PathsConfig
}

type SpotifyConfig struct {
	ClientID     string
	ClientSecret string
	RedirectURI  string
}

type HTTPConfig struct {
	ListenAddr string
}

type MQTTConfig struct {
	Host     string
	Port     int
	Username string
	Password string
	Topic    string
}

type PollingConfig struct {
	MinInterval       time.Duration
	MaxPlayingInterval time.Duration
	BoundaryLookahead  time.Duration
	IdleInterval       time.Duration
	MaxErrorBackoff    time.Duration
}

type PathsConfig struct {
	TokenFile string
}

type rawOptions struct {
	SpotifyClientID       string `json:"spotify_client_id"`
	SpotifyClientSecret   string `json:"spotify_client_secret"`
	SpotifyRedirectURI    string `json:"spotify_redirect_uri"`
	HTTPListenAddr        string `json:"http_listen_addr"`
	MQTTHost              string `json:"mqtt_host"`
	MQTTPort              int    `json:"mqtt_port"`
	MQTTUsername          string `json:"mqtt_username"`
	MQTTPassword          string `json:"mqtt_password"`
	MQTTTopic             string `json:"mqtt_topic"`
	TokenFile             string `json:"token_file"`
	MinPollSeconds        int    `json:"min_poll_seconds"`
	MaxPlayingPollSeconds int    `json:"max_playing_poll_seconds"`
	BoundaryLookaheadSeconds int `json:"boundary_lookahead_seconds"`
	IdlePollSeconds       int    `json:"idle_poll_seconds"`
	MaxErrorBackoffSeconds int    `json:"max_error_backoff_seconds"`
}

func Load(path string) (Config, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return Config{}, fmt.Errorf("read config %s: %w", path, err)
	}

	var raw rawOptions
	if err := json.Unmarshal(content, &raw); err != nil {
		return Config{}, fmt.Errorf("parse config %s: %w", path, err)
	}

	cfg := Config{
		Spotify: SpotifyConfig{
			ClientID:     raw.SpotifyClientID,
			ClientSecret: raw.SpotifyClientSecret,
			RedirectURI:  raw.SpotifyRedirectURI,
		},
		HTTP: HTTPConfig{ListenAddr: defaultString(raw.HTTPListenAddr, ":8099")},
		MQTT: MQTTConfig{
			Host:     raw.MQTTHost,
			Port:     defaultInt(raw.MQTTPort, 1883),
			Username: raw.MQTTUsername,
			Password: raw.MQTTPassword,
			Topic:    defaultString(raw.MQTTTopic, "spotiframe/now_playing"),
		},
		Polling: PollingConfig{
			MinInterval:        seconds(raw.MinPollSeconds, 5),
			MaxPlayingInterval: seconds(raw.MaxPlayingPollSeconds, 30),
			BoundaryLookahead:  seconds(raw.BoundaryLookaheadSeconds, 2),
			IdleInterval:       seconds(raw.IdlePollSeconds, 30),
			MaxErrorBackoff:    seconds(raw.MaxErrorBackoffSeconds, 300),
		},
		Paths: PathsConfig{TokenFile: defaultString(raw.TokenFile, "/data/spotiframe-token.json")},
	}

	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Validate() error {
	switch {
	case c.Spotify.ClientID == "":
		return errors.New("spotify_client_id is required")
	case c.Spotify.ClientSecret == "":
		return errors.New("spotify_client_secret is required")
	case c.Spotify.RedirectURI == "":
		return errors.New("spotify_redirect_uri is required")
	case c.MQTT.Host == "":
		return errors.New("mqtt_host is required")
	case c.MQTT.Port <= 0:
		return errors.New("mqtt_port must be positive")
	case c.MQTT.Topic == "":
		return errors.New("mqtt_topic is required")
	case c.HTTP.ListenAddr == "":
		return errors.New("http_listen_addr is required")
	case c.Paths.TokenFile == "":
		return errors.New("token_file is required")
	case c.Polling.MinInterval <= 0:
		return errors.New("min_poll_seconds must be positive")
	case c.Polling.MaxPlayingInterval < c.Polling.MinInterval:
		return errors.New("max_playing_poll_seconds must be greater than or equal to min_poll_seconds")
	case c.Polling.IdleInterval <= 0:
		return errors.New("idle_poll_seconds must be positive")
	case c.Polling.MaxErrorBackoff <= 0:
		return errors.New("max_error_backoff_seconds must be positive")
	default:
		return nil
	}
}

func defaultString(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func defaultInt(value, fallback int) int {
	if value == 0 {
		return fallback
	}
	return value
}

func seconds(value, fallback int) time.Duration {
	return time.Duration(defaultInt(value, fallback)) * time.Second
}
```

- [ ] **Step 4: Update module dependencies**

Modify `go.mod`:

```go
module github.com/straw-hat-sunny/spotiframe

go 1.26.4

require (
	github.com/eclipse/paho.mqtt.golang v1.5.0
	golang.org/x/oauth2 v0.30.0
)
```

Run:

```bash
go mod tidy
```

Expected: `go.sum` is created or updated.

- [ ] **Step 5: Run config tests**

Run:

```bash
go test ./internal/config
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add go.mod go.sum internal/config/config.go internal/config/config_test.go
git commit -m "feat: add producer config loading"
```

## Task 2: Add Minimal MQTT Payload Contract

**Files:**
- Create: `internal/payload/payload.go`
- Create: `internal/payload/payload_test.go`

- [ ] **Step 1: Write failing payload tests**

Create `internal/payload/payload_test.go`:

```go
package payload

import (
	"encoding/json"
	"testing"
)

func TestSnapshotJSONPlaying(t *testing.T) {
	art := "https://i.scdn.co/image/abc"
	s := Snapshot{SchemaVersion: 1, IsPlaying: true, AlbumArtURL: &art}

	got, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}

	want := `{"schema_version":1,"is_playing":true,"album_art_url":"https://i.scdn.co/image/abc"}`
	if string(got) != want {
		t.Fatalf("json = %s, want %s", got, want)
	}
}

func TestSnapshotJSONIdle(t *testing.T) {
	s := Idle()

	got, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}

	want := `{"schema_version":1,"is_playing":false,"album_art_url":null}`
	if string(got) != want {
		t.Fatalf("json = %s, want %s", got, want)
	}
}

func TestChangedIgnoresSameSnapshot(t *testing.T) {
	art := "https://i.scdn.co/image/abc"
	a := Snapshot{SchemaVersion: 1, IsPlaying: true, AlbumArtURL: &art}
	b := Snapshot{SchemaVersion: 1, IsPlaying: true, AlbumArtURL: &art}

	if Changed(a, b) {
		t.Fatal("Changed returned true for identical snapshots")
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/payload
```

Expected: FAIL because package `internal/payload` does not exist.

- [ ] **Step 3: Implement payload type**

Create `internal/payload/payload.go`:

```go
package payload

type Snapshot struct {
	SchemaVersion int     `json:"schema_version"`
	IsPlaying     bool    `json:"is_playing"`
	AlbumArtURL   *string `json:"album_art_url"`
}

func Playing(albumArtURL string) Snapshot {
	return Snapshot{
		SchemaVersion: 1,
		IsPlaying:     true,
		AlbumArtURL:   &albumArtURL,
	}
}

func Idle() Snapshot {
	return Snapshot{
		SchemaVersion: 1,
		IsPlaying:     false,
		AlbumArtURL:   nil,
	}
}

func Changed(previous, next Snapshot) bool {
	if previous.SchemaVersion != next.SchemaVersion {
		return true
	}
	if previous.IsPlaying != next.IsPlaying {
		return true
	}
	if previous.AlbumArtURL == nil && next.AlbumArtURL == nil {
		return false
	}
	if previous.AlbumArtURL == nil || next.AlbumArtURL == nil {
		return true
	}
	return *previous.AlbumArtURL != *next.AlbumArtURL
}
```

- [ ] **Step 4: Run payload tests**

Run:

```bash
go test ./internal/payload
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/payload/payload.go internal/payload/payload_test.go
git commit -m "feat: add MQTT payload contract"
```

## Task 3: Add Progress-Aware Scheduler

**Files:**
- Create: `internal/scheduler/scheduler.go`
- Create: `internal/scheduler/scheduler_test.go`

- [ ] **Step 1: Write failing scheduler tests**

Create `internal/scheduler/scheduler_test.go`:

```go
package scheduler

import (
	"testing"
	"time"
)

func testConfig() Config {
	return Config{
		MinInterval:        5 * time.Second,
		MaxPlayingInterval: 30 * time.Second,
		BoundaryLookahead:  2 * time.Second,
		IdleInterval:       30 * time.Second,
		MaxErrorBackoff:    5 * time.Minute,
	}
}

func TestNextPlayingPollNearBoundary(t *testing.T) {
	got := Next(testConfig(), State{
		IsPlaying:  true,
		Duration:   120 * time.Second,
		Progress:   110 * time.Second,
		ErrorCount: 0,
	})

	if got != 8*time.Second {
		t.Fatalf("Next = %s, want 8s", got)
	}
}

func TestNextPlayingPollClampsToMax(t *testing.T) {
	got := Next(testConfig(), State{
		IsPlaying: true,
		Duration:  180 * time.Second,
		Progress:  10 * time.Second,
	})

	if got != 30*time.Second {
		t.Fatalf("Next = %s, want 30s", got)
	}
}

func TestNextIdleUsesIdleInterval(t *testing.T) {
	got := Next(testConfig(), State{IsPlaying: false})
	if got != 30*time.Second {
		t.Fatalf("Next = %s, want 30s", got)
	}
}

func TestNextErrorBackoff(t *testing.T) {
	got := Next(testConfig(), State{ErrorCount: 3})
	if got != 40*time.Second {
		t.Fatalf("Next = %s, want 40s", got)
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/scheduler
```

Expected: FAIL because package `internal/scheduler` does not exist.

- [ ] **Step 3: Implement scheduler**

Create `internal/scheduler/scheduler.go`:

```go
package scheduler

import "time"

type Config struct {
	MinInterval        time.Duration
	MaxPlayingInterval time.Duration
	BoundaryLookahead  time.Duration
	IdleInterval       time.Duration
	MaxErrorBackoff    time.Duration
}

type State struct {
	IsPlaying  bool
	Duration   time.Duration
	Progress   time.Duration
	ErrorCount int
	RetryAfter time.Duration
}

func Next(cfg Config, state State) time.Duration {
	if state.RetryAfter > 0 {
		return clamp(state.RetryAfter, cfg.MinInterval, cfg.MaxErrorBackoff)
	}
	if state.ErrorCount > 0 {
		backoff := cfg.MinInterval
		for i := 1; i < state.ErrorCount; i++ {
			backoff *= 2
		}
		return clamp(backoff, cfg.MinInterval, cfg.MaxErrorBackoff)
	}
	if !state.IsPlaying || state.Duration <= 0 {
		return cfg.IdleInterval
	}

	remaining := state.Duration - state.Progress - cfg.BoundaryLookahead
	return clamp(remaining, cfg.MinInterval, cfg.MaxPlayingInterval)
}

func clamp(value, min, max time.Duration) time.Duration {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}
```

- [ ] **Step 4: Run scheduler tests**

Run:

```bash
go test ./internal/scheduler
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/scheduler/scheduler.go internal/scheduler/scheduler_test.go
git commit -m "feat: add progress-aware polling scheduler"
```

## Task 4: Add Spotify Response Mapping

**Files:**
- Create: `internal/spotify/client.go`
- Create: `internal/spotify/client_test.go`

- [ ] **Step 1: Write failing Spotify client tests**

Create `internal/spotify/client_test.go`:

```go
package spotify

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestCurrentlyPlayingMapsArtwork(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/me/player/currently-playing" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"is_playing": true,
			"progress_ms": 42000,
			"item": {
				"type": "track",
				"id": "track-id",
				"duration_ms": 210000,
				"album": {
					"images": [
						{"url": "https://i.scdn.co/image/large", "height": 640, "width": 640},
						{"url": "https://i.scdn.co/image/small", "height": 64, "width": 64}
					]
				}
			}
		}`))
	}))
	defer server.Close()

	client := NewClient(server.URL, server.Client())
	got, err := client.CurrentlyPlaying(context.Background())
	if err != nil {
		t.Fatal(err)
	}

	if !got.IsPlaying {
		t.Fatal("IsPlaying = false, want true")
	}
	if got.AlbumArtURL != "https://i.scdn.co/image/large" {
		t.Fatalf("AlbumArtURL = %q", got.AlbumArtURL)
	}
	if got.Duration != 210*time.Second {
		t.Fatalf("Duration = %s", got.Duration)
	}
	if got.Progress != 42*time.Second {
		t.Fatalf("Progress = %s", got.Progress)
	}
}

func TestCurrentlyPlayingNoContentIsIdle(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	client := NewClient(server.URL, server.Client())
	got, err := client.CurrentlyPlaying(context.Background())
	if err != nil {
		t.Fatal(err)
	}

	if got.IsPlaying {
		t.Fatal("IsPlaying = true, want false")
	}
	if got.AlbumArtURL != "" {
		t.Fatalf("AlbumArtURL = %q, want empty", got.AlbumArtURL)
	}
}

func TestCurrentlyPlayingRateLimit(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Retry-After", "7")
		w.WriteHeader(http.StatusTooManyRequests)
	}))
	defer server.Close()

	client := NewClient(server.URL, server.Client())
	_, err := client.CurrentlyPlaying(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	var rateErr *RateLimitError
	if !AsRateLimit(err, &rateErr) {
		t.Fatalf("error type = %T, want RateLimitError", err)
	}
	if rateErr.RetryAfter != 7*time.Second {
		t.Fatalf("RetryAfter = %s", rateErr.RetryAfter)
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/spotify
```

Expected: FAIL because package `internal/spotify` does not exist.

- [ ] **Step 3: Implement Spotify client**

Create `internal/spotify/client.go`:

```go
package spotify

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"time"
)

type Client struct {
	baseURL    string
	httpClient *http.Client
}

type Playback struct {
	IsPlaying   bool
	AlbumArtURL string
	Duration    time.Duration
	Progress    time.Duration
}

type RateLimitError struct {
	RetryAfter time.Duration
}

func (e *RateLimitError) Error() string {
	return fmt.Sprintf("spotify rate limited; retry after %s", e.RetryAfter)
}

type AuthError struct {
	StatusCode int
}

func (e *AuthError) Error() string {
	return fmt.Sprintf("spotify auth failed with status %d", e.StatusCode)
}

func NewClient(baseURL string, httpClient *http.Client) *Client {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	return &Client{baseURL: baseURL, httpClient: httpClient}
}

func (c *Client) CurrentlyPlaying(ctx context.Context) (Playback, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/v1/me/player/currently-playing", nil)
	if err != nil {
		return Playback{}, err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return Playback{}, err
	}
	defer resp.Body.Close()

	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusNoContent:
		return Playback{IsPlaying: false}, nil
	case http.StatusUnauthorized, http.StatusForbidden:
		return Playback{}, &AuthError{StatusCode: resp.StatusCode}
	case http.StatusTooManyRequests:
		return Playback{}, &RateLimitError{RetryAfter: retryAfter(resp.Header.Get("Retry-After"))}
	default:
		return Playback{}, fmt.Errorf("spotify currently-playing status %d", resp.StatusCode)
	}

	var body currentlyPlayingResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return Playback{}, err
	}
	if body.Item == nil || len(body.Item.Album.Images) == 0 || !body.IsPlaying {
		return Playback{IsPlaying: false}, nil
	}

	return Playback{
		IsPlaying:   true,
		AlbumArtURL: body.Item.Album.Images[0].URL,
		Duration:    time.Duration(body.Item.DurationMS) * time.Millisecond,
		Progress:    time.Duration(body.ProgressMS) * time.Millisecond,
	}, nil
}

func AsRateLimit(err error, target **RateLimitError) bool {
	return errors.As(err, target)
}

func retryAfter(value string) time.Duration {
	seconds, err := strconv.Atoi(value)
	if err != nil || seconds <= 0 {
		return 0
	}
	return time.Duration(seconds) * time.Second
}

type currentlyPlayingResponse struct {
	IsPlaying  bool `json:"is_playing"`
	ProgressMS int `json:"progress_ms"`
	Item       *struct {
		Type       string `json:"type"`
		ID         string `json:"id"`
		DurationMS int    `json:"duration_ms"`
		Album      struct {
			Images []struct {
				URL string `json:"url"`
			} `json:"images"`
		} `json:"album"`
	} `json:"item"`
}
```

- [ ] **Step 4: Run Spotify tests**

Run:

```bash
go test ./internal/spotify
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/spotify/client.go internal/spotify/client_test.go
git commit -m "feat: add Spotify currently playing client"
```

## Task 5: Add Token Store

**Files:**
- Create: `internal/auth/store.go`
- Create: `internal/auth/store_test.go`

- [ ] **Step 1: Write failing token store tests**

Create `internal/auth/store_test.go`:

```go
package auth

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"golang.org/x/oauth2"
)

func TestTokenStoreRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "token.json")
	store := FileTokenStore{Path: path}
	token := &oauth2.Token{
		AccessToken:  "access",
		RefreshToken: "refresh",
		TokenType:    "Bearer",
		Expiry:       time.Unix(2000, 0).UTC(),
	}

	if err := store.Save(token); err != nil {
		t.Fatal(err)
	}
	got, err := store.Load()
	if err != nil {
		t.Fatal(err)
	}

	if got.AccessToken != "access" || got.RefreshToken != "refresh" {
		t.Fatalf("token = %#v", got)
	}
}

func TestTokenStoreMissingFile(t *testing.T) {
	store := FileTokenStore{Path: filepath.Join(t.TempDir(), "missing.json")}
	_, err := store.Load()
	if !IsTokenMissing(err) {
		t.Fatalf("err = %v, want token missing", err)
	}
}

func TestTokenStoreFileMode(t *testing.T) {
	path := filepath.Join(t.TempDir(), "token.json")
	store := FileTokenStore{Path: path}
	if err := store.Save(&oauth2.Token{RefreshToken: "refresh"}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("mode = %v, want 0600", info.Mode().Perm())
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/auth
```

Expected: FAIL because package `internal/auth` does not exist.

- [ ] **Step 3: Implement token store**

Create `internal/auth/store.go`:

```go
package auth

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"golang.org/x/oauth2"
)

var ErrTokenMissing = errors.New("spotify token is missing")

type FileTokenStore struct {
	Path string
}

func (s FileTokenStore) Load() (*oauth2.Token, error) {
	content, err := os.ReadFile(s.Path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, ErrTokenMissing
	}
	if err != nil {
		return nil, fmt.Errorf("read token file: %w", err)
	}
	var token oauth2.Token
	if err := json.Unmarshal(content, &token); err != nil {
		return nil, fmt.Errorf("parse token file: %w", err)
	}
	return &token, nil
}

func (s FileTokenStore) Save(token *oauth2.Token) error {
	if token == nil {
		return errors.New("token is nil")
	}
	if err := os.MkdirAll(filepath.Dir(s.Path), 0o700); err != nil {
		return fmt.Errorf("create token directory: %w", err)
	}
	content, err := json.MarshalIndent(token, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal token: %w", err)
	}
	return os.WriteFile(s.Path, content, 0o600)
}

func IsTokenMissing(err error) bool {
	return errors.Is(err, ErrTokenMissing)
}
```

- [ ] **Step 4: Run token store tests**

Run:

```bash
go test ./internal/auth
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/auth/store.go internal/auth/store_test.go
git commit -m "feat: add Spotify token store"
```

## Task 6: Add OAuth And Health HTTP Server

**Files:**
- Create: `internal/auth/server.go`
- Modify: `internal/auth/server_test.go`

- [ ] **Step 1: Write failing auth server tests**

Create `internal/auth/server_test.go`:

```go
package auth

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"golang.org/x/oauth2"
)

type fakeExchanger struct {
	code string
}

func (f *fakeExchanger) AuthCodeURL(state string) string {
	return "https://accounts.spotify.com/authorize?state=" + state
}

func (f *fakeExchanger) Exchange(code string) (*oauth2.Token, error) {
	f.code = code
	return &oauth2.Token{RefreshToken: "refresh"}, nil
}

type memoryStore struct {
	token *oauth2.Token
}

func (s *memoryStore) Save(token *oauth2.Token) error {
	s.token = token
	return nil
}

func TestLoginRedirectsToSpotify(t *testing.T) {
	exchanger := &fakeExchanger{}
	server := NewServer(exchanger, &memoryStore{}, func() bool { return false })

	req := httptest.NewRequest(http.MethodGet, "/login", nil)
	res := httptest.NewRecorder()
	server.ServeHTTP(res, req)

	if res.Code != http.StatusFound {
		t.Fatalf("status = %d, want 302", res.Code)
	}
	if !strings.Contains(res.Header().Get("Location"), "https://accounts.spotify.com/authorize") {
		t.Fatalf("Location = %q", res.Header().Get("Location"))
	}
}

func TestCallbackRejectsBadState(t *testing.T) {
	server := NewServer(&fakeExchanger{}, &memoryStore{}, func() bool { return false })
	httptest.NewRecorder()

	loginReq := httptest.NewRequest(http.MethodGet, "/login", nil)
	loginRes := httptest.NewRecorder()
	server.ServeHTTP(loginRes, loginReq)

	req := httptest.NewRequest(http.MethodGet, "/callback?code=abc&state=wrong", nil)
	res := httptest.NewRecorder()
	server.ServeHTTP(res, req)

	if res.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", res.Code)
	}
}

func TestHealthReportsAuthRequired(t *testing.T) {
	server := NewServer(&fakeExchanger{}, &memoryStore{}, func() bool { return false })
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	res := httptest.NewRecorder()

	server.ServeHTTP(res, req)

	if res.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", res.Code)
	}
	if !strings.Contains(res.Body.String(), `"authenticated":false`) {
		t.Fatalf("body = %s", res.Body.String())
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/auth
```

Expected: FAIL because `NewServer` is undefined.

- [ ] **Step 3: Implement auth server**

Create `internal/auth/server.go`:

```go
package auth

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"sync"

	"golang.org/x/oauth2"
)

type Exchanger interface {
	AuthCodeURL(state string) string
	Exchange(code string) (*oauth2.Token, error)
}

type TokenSaver interface {
	Save(token *oauth2.Token) error
}

type Server struct {
	exchanger       Exchanger
	store           TokenSaver
	authenticated   func() bool
	mu              sync.Mutex
	lastState       string
}

func NewServer(exchanger Exchanger, store TokenSaver, authenticated func() bool) *Server {
	return &Server{exchanger: exchanger, store: store, authenticated: authenticated}
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch r.URL.Path {
	case "/login":
		s.login(w, r)
	case "/callback":
		s.callback(w, r)
	case "/healthz":
		s.health(w, r)
	default:
		http.NotFound(w, r)
	}
}

func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	state := randomState()
	s.mu.Lock()
	s.lastState = state
	s.mu.Unlock()
	http.Redirect(w, r, s.exchanger.AuthCodeURL(state), http.StatusFound)
}

func (s *Server) callback(w http.ResponseWriter, r *http.Request) {
	state := r.URL.Query().Get("state")
	code := r.URL.Query().Get("code")
	s.mu.Lock()
	expected := s.lastState
	s.mu.Unlock()
	if state == "" || state != expected {
		http.Error(w, "state mismatch", http.StatusBadRequest)
		return
	}
	if code == "" {
		http.Error(w, "missing code", http.StatusBadRequest)
		return
	}
	token, err := s.exchanger.Exchange(code)
	if err != nil {
		http.Error(w, "token exchange failed", http.StatusBadGateway)
		return
	}
	if err := s.store.Save(token); err != nil {
		http.Error(w, "token save failed", http.StatusInternalServerError)
		return
	}
	_, _ = w.Write([]byte("SpotiFrame Spotify authentication complete."))
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]bool{"authenticated": s.authenticated()})
}

func randomState() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		panic(err)
	}
	return hex.EncodeToString(bytes[:])
}
```

- [ ] **Step 4: Run auth tests**

Run:

```bash
go test ./internal/auth
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/auth/server.go internal/auth/server_test.go
git commit -m "feat: add OAuth callback server"
```

## Task 7: Add MQTT Publisher

**Files:**
- Create: `internal/mqtt/publisher.go`
- Create: `internal/mqtt/publisher_test.go`

- [ ] **Step 1: Write failing publisher tests**

Create `internal/mqtt/publisher_test.go`:

```go
package mqtt

import (
	"context"
	"testing"
)

type fakeClient struct {
	topic    string
	payload  []byte
	retained bool
}

func (f *fakeClient) Publish(topic string, qos byte, retained bool, payload interface{}) Token {
	f.topic = topic
	f.retained = retained
	f.payload = payload.([]byte)
	return fakeToken{}
}

type fakeToken struct{}

func (fakeToken) Wait() bool { return true }
func (fakeToken) Error() error { return nil }

func TestPublisherPublishesRetainedJSON(t *testing.T) {
	client := &fakeClient{}
	publisher := Publisher{Client: client, Topic: "spotiframe/now_playing"}

	art := "https://i.scdn.co/image/abc"
	err := publisher.Publish(context.Background(), Snapshot{
		SchemaVersion: 1,
		IsPlaying: true,
		AlbumArtURL: &art,
	})
	if err != nil {
		t.Fatal(err)
	}
	if client.topic != "spotiframe/now_playing" {
		t.Fatalf("topic = %q", client.topic)
	}
	if !client.retained {
		t.Fatal("retained = false, want true")
	}
	if string(client.payload) != `{"schema_version":1,"is_playing":true,"album_art_url":"https://i.scdn.co/image/abc"}` {
		t.Fatalf("payload = %s", client.payload)
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/mqtt
```

Expected: FAIL because package `internal/mqtt` does not exist.

- [ ] **Step 3: Implement publisher**

Create `internal/mqtt/publisher.go`:

```go
package mqtt

import (
	"context"
	"encoding/json"

	"github.com/straw-hat-sunny/spotiframe/internal/payload"
)

type Snapshot = payload.Snapshot

type Token interface {
	Wait() bool
	Error() error
}

type Client interface {
	Publish(topic string, qos byte, retained bool, payload interface{}) Token
}

type Publisher struct {
	Client Client
	Topic  string
}

func (p Publisher) Publish(ctx context.Context, snapshot Snapshot) error {
	content, err := json.Marshal(snapshot)
	if err != nil {
		return err
	}
	token := p.Client.Publish(p.Topic, 0, true, content)
	done := make(chan struct{})
	go func() {
		token.Wait()
		close(done)
	}()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-done:
		return token.Error()
	}
}
```

- [ ] **Step 4: Run publisher tests**

Run:

```bash
go test ./internal/mqtt
```

Expected: PASS.

- [ ] **Step 5: Add Paho factory**

Extend `internal/mqtt/publisher.go`:

```go
func NewPahoClient(brokerURL, clientID, username, password string) Client {
	opts := paho.NewClientOptions()
	opts.AddBroker(brokerURL)
	opts.SetClientID(clientID)
	opts.SetAutoReconnect(true)
	opts.SetConnectRetry(true)
	if username != "" {
		opts.SetUsername(username)
		opts.SetPassword(password)
	}
	return paho.NewClient(opts)
}
```

Add this import to the same file:

```go
import paho "github.com/eclipse/paho.mqtt.golang"
```

Run:

```bash
go test ./internal/mqtt
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/mqtt/publisher.go internal/mqtt/publisher_test.go
git commit -m "feat: add retained MQTT publisher"
```

## Task 8: Add OAuth Exchanger Wiring

**Files:**
- Create: `internal/auth/oauth.go`
- Create: `internal/auth/oauth_test.go`

- [ ] **Step 1: Write failing OAuth exchanger test**

Create `internal/auth/oauth_test.go`:

```go
package auth

import (
	"strings"
	"testing"
)

func TestSpotifyOAuthAuthCodeURL(t *testing.T) {
	oauth := NewSpotifyOAuth("client-id", "client-secret", "http://localhost:8099/callback")

	got := oauth.AuthCodeURL("state-value")

	if !strings.Contains(got, "client_id=client-id") {
		t.Fatalf("AuthCodeURL missing client_id: %s", got)
	}
	if !strings.Contains(got, "state=state-value") {
		t.Fatalf("AuthCodeURL missing state: %s", got)
	}
	if !strings.Contains(got, "user-read-currently-playing") {
		t.Fatalf("AuthCodeURL missing scope: %s", got)
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/auth
```

Expected: FAIL because `NewSpotifyOAuth` is undefined.

- [ ] **Step 3: Implement OAuth exchanger**

Create `internal/auth/oauth.go`:

```go
package auth

import (
	"context"
	"net/http"

	"golang.org/x/oauth2"
	"golang.org/x/oauth2/spotify"
)

type SpotifyOAuth struct {
	config *oauth2.Config
}

func NewSpotifyOAuth(clientID, clientSecret, redirectURI string) *SpotifyOAuth {
	return &SpotifyOAuth{
		config: &oauth2.Config{
			ClientID:     clientID,
			ClientSecret: clientSecret,
			RedirectURL:  redirectURI,
			Scopes:       []string{"user-read-currently-playing"},
			Endpoint:     spotify.Endpoint,
		},
	}
}

func (s *SpotifyOAuth) AuthCodeURL(state string) string {
	return s.config.AuthCodeURL(state, oauth2.AccessTypeOffline)
}

func (s *SpotifyOAuth) Exchange(code string) (*oauth2.Token, error) {
	return s.config.Exchange(context.Background(), code)
}

func (s *SpotifyOAuth) HTTPClient(ctx context.Context, token *oauth2.Token) *http.Client {
	return s.config.Client(ctx, token)
}
```

- [ ] **Step 4: Run auth tests**

Run:

```bash
go test ./internal/auth
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/auth/oauth.go internal/auth/oauth_test.go
git commit -m "feat: add Spotify OAuth wiring"
```

## Task 9: Add Application Orchestration

**Files:**
- Create: `internal/app/app.go`
- Create: `internal/app/app_test.go`

- [ ] **Step 1: Write failing app tests**

Create `internal/app/app_test.go`:

```go
package app

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/straw-hat-sunny/spotiframe/internal/spotify"
)

type fakeSpotify struct {
	playbacks []spotify.Playback
	errs      []error
	calls     int
}

func (f *fakeSpotify) CurrentlyPlaying(ctx context.Context) (spotify.Playback, error) {
	idx := f.calls
	f.calls++
	if idx < len(f.errs) && f.errs[idx] != nil {
		return spotify.Playback{}, f.errs[idx]
	}
	return f.playbacks[idx], nil
}

type fakePublisher struct {
	count int
}

func (f *fakePublisher) Publish(ctx context.Context, snapshot Snapshot) error {
	f.count++
	return nil
}

func TestPollOncePublishesOnlyOnChange(t *testing.T) {
	spot := &fakeSpotify{playbacks: []spotify.Playback{
		{IsPlaying: true, AlbumArtURL: "https://i.scdn.co/image/a"},
		{IsPlaying: true, AlbumArtURL: "https://i.scdn.co/image/a"},
		{IsPlaying: true, AlbumArtURL: "https://i.scdn.co/image/b"},
	}}
	pub := &fakePublisher{}
	runner := NewRunner(spot, pub)

	for i := 0; i < 3; i++ {
		if err := runner.PollOnce(context.Background()); err != nil {
			t.Fatal(err)
		}
	}

	if pub.count != 2 {
		t.Fatalf("publish count = %d, want 2", pub.count)
	}
}

func TestPollOnceDoesNotPublishIdleOnTemporaryError(t *testing.T) {
	spot := &fakeSpotify{errs: []error{errors.New("network down")}}
	pub := &fakePublisher{}
	runner := NewRunner(spot, pub)

	err := runner.PollOnce(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	if pub.count != 0 {
		t.Fatalf("publish count = %d, want 0", pub.count)
	}
}

func TestPlaybackToSchedulerState(t *testing.T) {
	state := SchedulerState(spotify.Playback{
		IsPlaying: true,
		Duration: 210 * time.Second,
		Progress: 42 * time.Second,
	}, 0, 0)

	if !state.IsPlaying || state.Duration != 210*time.Second || state.Progress != 42*time.Second {
		t.Fatalf("state = %#v", state)
	}
}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
go test ./internal/app
```

Expected: FAIL because package `internal/app` does not exist.

- [ ] **Step 3: Implement runner**

Create `internal/app/app.go`:

```go
package app

import (
	"context"
	"time"

	"github.com/straw-hat-sunny/spotiframe/internal/payload"
	"github.com/straw-hat-sunny/spotiframe/internal/scheduler"
	"github.com/straw-hat-sunny/spotiframe/internal/spotify"
)

type Snapshot = payload.Snapshot

type Spotify interface {
	CurrentlyPlaying(ctx context.Context) (spotify.Playback, error)
}

type Publisher interface {
	Publish(ctx context.Context, snapshot Snapshot) error
}

type Runner struct {
	spotify   Spotify
	publisher Publisher
	last      Snapshot
	hasLast   bool
	playback  spotify.Playback
}

func NewRunner(spotify Spotify, publisher Publisher) *Runner {
	return &Runner{spotify: spotify, publisher: publisher}
}

func (r *Runner) PollOnce(ctx context.Context) error {
	playback, err := r.spotify.CurrentlyPlaying(ctx)
	if err != nil {
		return err
	}
	r.playback = playback
	next := snapshotFromPlayback(playback)
	if r.hasLast && !payload.Changed(r.last, next) {
		return nil
	}
	if err := r.publisher.Publish(ctx, next); err != nil {
		return err
	}
	r.last = next
	r.hasLast = true
	return nil
}

func SchedulerState(playback spotify.Playback, errorCount int, retryAfter time.Duration) scheduler.State {
	return scheduler.State{
		IsPlaying:  playback.IsPlaying,
		Duration:   playback.Duration,
		Progress:   playback.Progress,
		ErrorCount: errorCount,
		RetryAfter: retryAfter,
	}
}

func snapshotFromPlayback(playback spotify.Playback) Snapshot {
	if !playback.IsPlaying || playback.AlbumArtURL == "" {
		return payload.Idle()
	}
	return payload.Playing(playback.AlbumArtURL)
}
```

- [ ] **Step 4: Run app tests**

Run:

```bash
go test ./internal/app
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/app/app.go internal/app/app_test.go
git commit -m "feat: add producer polling runner"
```

## Task 10: Add CLI Entrypoint

**Files:**
- Create: `cmd/spotiframe-producer/main.go`

- [ ] **Step 1: Write the entrypoint**

Create `cmd/spotiframe-producer/main.go`:

```go
package main

import (
	"context"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/straw-hat-sunny/spotiframe/internal/auth"
	"github.com/straw-hat-sunny/spotiframe/internal/config"
)

func main() {
	configPath := flag.String("config", "/data/options.json", "path to SpotiFrame producer JSON config")
	flag.Parse()

	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	tokenStore := auth.FileTokenStore{Path: cfg.Paths.TokenFile}
	oauth := auth.NewSpotifyOAuth(cfg.Spotify.ClientID, cfg.Spotify.ClientSecret, cfg.Spotify.RedirectURI)
	authenticated := func() bool {
		_, err := tokenStore.Load()
		return err == nil
	}
	authServer := auth.NewServer(oauth, tokenStore, authenticated)

	httpServer := &http.Server{
		Addr:    cfg.HTTP.ListenAddr,
		Handler: authServer,
	}

	go func() {
		log.Printf("auth and health server listening on %s", cfg.HTTP.ListenAddr)
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("http server error: %v", err)
			stop()
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		log.Printf("http shutdown error: %v", err)
	}
}
```

- [ ] **Step 2: Verify entrypoint builds**

Run:

```bash
go test ./...
go build ./cmd/spotiframe-producer
```

Expected: both commands PASS.

- [ ] **Step 3: Commit**

```bash
git add cmd/spotiframe-producer/main.go
git commit -m "feat: add producer command entrypoint"
```

## Task 11: Wire Full Runtime Loop

**Files:**
- Modify: `cmd/spotiframe-producer/main.go`
- Modify: `internal/mqtt/publisher.go`
- Modify: `internal/app/app.go`

- [ ] **Step 1: Add MQTT connect helper**

Extend `internal/mqtt/publisher.go`:

```go
func Connect(client Client) error {
	type connector interface {
		Connect() Token
	}
	c, ok := client.(connector)
	if !ok {
		return nil
	}
	token := c.Connect()
	token.Wait()
	return token.Error()
}
```

- [ ] **Step 2: Add app loop**

Extend `internal/app/app.go`:

```go
func (r *Runner) Run(ctx context.Context, cfg scheduler.Config) error {
	errorCount := 0
	for {
		err := r.PollOnce(ctx)
		retryAfter := time.Duration(0)
		if err != nil {
			errorCount++
			var rateLimit *spotify.RateLimitError
			if spotify.AsRateLimit(err, &rateLimit) {
				retryAfter = rateLimit.RetryAfter
			}
		} else {
			errorCount = 0
		}

		delay := scheduler.Next(cfg, SchedulerState(r.playback, errorCount, retryAfter))
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}
```

- [ ] **Step 3: Update main to load token and start producer loop**

In `cmd/spotiframe-producer/main.go`, after starting the HTTP server, add:

```go
token, err := waitForToken(ctx, tokenStore, 5*time.Second)
if err != nil {
	log.Fatalf("load token: %v", err)
}

spotifyHTTP := oauth.HTTPClient(ctx, token)
spotifyClient := spotify.NewClient("https://api.spotify.com", spotifyHTTP)
brokerURL := fmt.Sprintf("tcp://%s:%d", cfg.MQTT.Host, cfg.MQTT.Port)
mqttClient := mqtt.NewPahoClient(brokerURL, "spotiframe-producer", cfg.MQTT.Username, cfg.MQTT.Password)
if err := mqtt.Connect(mqttClient); err != nil {
	log.Fatalf("connect mqtt: %v", err)
}
publisher := mqtt.Publisher{Client: mqttClient, Topic: cfg.MQTT.Topic}
runner := app.NewRunner(spotifyClient, publisher)

schedulerConfig := scheduler.Config{
	MinInterval:        cfg.Polling.MinInterval,
	MaxPlayingInterval: cfg.Polling.MaxPlayingInterval,
	BoundaryLookahead:  cfg.Polling.BoundaryLookahead,
	IdleInterval:       cfg.Polling.IdleInterval,
	MaxErrorBackoff:    cfg.Polling.MaxErrorBackoff,
}
if err := runner.Run(ctx, schedulerConfig); err != nil && ctx.Err() == nil {
	log.Fatalf("run producer: %v", err)
}
```

Add this helper to `cmd/spotiframe-producer/main.go`:

```go
type tokenLoader interface {
	Load() (*oauth2.Token, error)
}

func waitForToken(ctx context.Context, store tokenLoader, interval time.Duration) (*oauth2.Token, error) {
	for {
		token, err := store.Load()
		if err == nil {
			return token, nil
		}
		if !auth.IsTokenMissing(err) {
			return nil, err
		}
		log.Printf("Spotify authentication required; open /login on this add-on")
		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil, ctx.Err()
		case <-timer.C:
		}
	}
}
```

Add these imports:

```go
import (
	"fmt"

	"github.com/straw-hat-sunny/spotiframe/internal/app"
	"github.com/straw-hat-sunny/spotiframe/internal/mqtt"
	"github.com/straw-hat-sunny/spotiframe/internal/scheduler"
	"github.com/straw-hat-sunny/spotiframe/internal/spotify"
	"golang.org/x/oauth2"
)
```

- [ ] **Step 4: Verify all Go packages**

Run:

```bash
go test ./...
go build ./cmd/spotiframe-producer
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add cmd/spotiframe-producer/main.go internal/app/app.go internal/mqtt/publisher.go
git commit -m "feat: wire producer runtime loop"
```

## Task 12: Add Home Assistant Add-on Packaging

**Files:**
- Create: `addons/spotiframe-producer/config.yaml`
- Create: `addons/spotiframe-producer/Dockerfile`
- Create: `addons/spotiframe-producer/run.sh`
- Create: `addons/spotiframe-producer/README.md`
- Create: `addons/spotiframe-producer/DOCS.md`

- [ ] **Step 1: Create add-on config**

Create `addons/spotiframe-producer/config.yaml`:

```yaml
name: "SpotiFrame Producer"
version: "0.1.0"
slug: "spotiframe_producer"
description: "Publishes the current Spotify album art URL to MQTT"
arch:
  - aarch64
  - amd64
startup: application
boot: auto
init: false
ports:
  8099/tcp: 8099
ports_description:
  8099/tcp: "Spotify OAuth callback and health endpoint"
options:
  spotify_client_id: null
  spotify_client_secret: null
  spotify_redirect_uri: "http://homeassistant.local:8099/callback"
  http_listen_addr: ":8099"
  mqtt_host: "core-mosquitto"
  mqtt_port: 1883
  mqtt_username: ""
  mqtt_password: ""
  mqtt_topic: "spotiframe/now_playing"
  min_poll_seconds: 5
  max_playing_poll_seconds: 30
  boundary_lookahead_seconds: 2
  idle_poll_seconds: 30
  max_error_backoff_seconds: 300
schema:
  spotify_client_id: str
  spotify_client_secret: password
  spotify_redirect_uri: url
  http_listen_addr: str
  mqtt_host: str
  mqtt_port: port
  mqtt_username: str?
  mqtt_password: password?
  mqtt_topic: str
  min_poll_seconds: "int(1,300)"
  max_playing_poll_seconds: "int(1,600)"
  boundary_lookahead_seconds: "int(0,30)"
  idle_poll_seconds: "int(5,600)"
  max_error_backoff_seconds: "int(5,1800)"
```

- [ ] **Step 2: Create Dockerfile**

Create `addons/spotiframe-producer/Dockerfile`:

```dockerfile
FROM golang:1.26-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/spotiframe-producer ./cmd/spotiframe-producer

FROM ghcr.io/home-assistant/base:latest

LABEL \
  io.hass.version="0.1.0" \
  io.hass.type="app" \
  io.hass.arch="aarch64|amd64"

COPY --from=builder /out/spotiframe-producer /usr/bin/spotiframe-producer
COPY addons/spotiframe-producer/run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
```

- [ ] **Step 3: Create run script**

Create `addons/spotiframe-producer/run.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

exec /usr/bin/spotiframe-producer -config /data/options.json
```

- [ ] **Step 4: Create add-on docs**

Create `addons/spotiframe-producer/README.md`:

```markdown
# SpotiFrame Producer

SpotiFrame Producer is a Home Assistant add-on that publishes the current Spotify album artwork URL to MQTT.
```

Create `addons/spotiframe-producer/DOCS.md`:

```markdown
# SpotiFrame Producer

## Setup

1. Create a Spotify app in the Spotify developer dashboard.
2. Add the configured redirect URI, for example `http://homeassistant.local:8099/callback`.
3. Configure the add-on with the Spotify client ID, Spotify client secret, MQTT broker settings, and MQTT topic.
4. Start the add-on.
5. Open `http://homeassistant.local:8099/login` and complete Spotify authorization.

## MQTT Payload

The add-on publishes retained JSON to `spotiframe/now_playing` by default.

```json
{
  "schema_version": 1,
  "is_playing": true,
  "album_art_url": "https://i.scdn.co/image/..."
}
```

When nothing is playing:

```json
{
  "schema_version": 1,
  "is_playing": false,
  "album_art_url": null
}
```

## Health

Open `/healthz` on the configured HTTP port to confirm the add-on process is running and whether Spotify authentication is complete.
```

- [ ] **Step 5: Verify packaging files**

Run:

```bash
test -x addons/spotiframe-producer/run.sh
go test ./...
```

Expected: both commands PASS.

- [ ] **Step 6: Commit**

```bash
git add addons/spotiframe-producer/config.yaml addons/spotiframe-producer/Dockerfile addons/spotiframe-producer/run.sh addons/spotiframe-producer/README.md addons/spotiframe-producer/DOCS.md
git commit -m "feat: add Home Assistant add-on packaging"
```

## Task 13: Update Repository Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README content**

Modify `README.md`:

```markdown
## SpotiFrame

SpotiFrame displays the artwork for the currently playing Spotify track on a picture frame.

The first component is `spotiframe-producer`, a lightweight Go Home Assistant add-on that:

- authenticates with Spotify using a one-time browser flow,
- polls the current playback state,
- publishes a retained MQTT JSON payload with `schema_version`, `is_playing`, and `album_art_url`.

The Raspberry Pi picture-frame consumer is intentionally outside the first implementation.

### Producer Layout

- `cmd/spotiframe-producer`: producer command entrypoint.
- `internal/*`: focused Go packages for config, auth, Spotify, scheduling, MQTT, and app orchestration.
- `addons/spotiframe-producer`: Home Assistant add-on packaging.

### Local Development

Create a JSON config file matching the add-on options, then run:

```bash
go run ./cmd/spotiframe-producer -config ./local.options.json
```
```

- [ ] **Step 2: Verify all tests**

Run:

```bash
go test ./...
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document SpotiFrame producer"
```

## Task 14: Final Verification

**Files:**
- No edits unless verification exposes a defect in a file from an earlier task.

- [ ] **Step 1: Run complete Go verification**

Run:

```bash
go test ./...
go build ./cmd/spotiframe-producer
```

Expected: both commands PASS.

- [ ] **Step 2: Build add-on image locally**

Run:

```bash
docker build -f addons/spotiframe-producer/Dockerfile -t spotiframe-producer:test .
```

Expected: image builds successfully.

- [ ] **Step 3: Smoke test local config validation**

Create `/tmp/spotiframe-options.json`:

```json
{
  "spotify_client_id": "client-id",
  "spotify_client_secret": "client-secret",
  "spotify_redirect_uri": "http://localhost:8099/callback",
  "http_listen_addr": ":8099",
  "mqtt_host": "localhost",
  "mqtt_port": 1883,
  "mqtt_topic": "spotiframe/now_playing"
}
```

Run:

```bash
go run ./cmd/spotiframe-producer -config /tmp/spotiframe-options.json
```

Expected: process starts, logs that Spotify authentication is required, and serves `/healthz`. Stop it with `Ctrl-C`.

- [ ] **Step 4: Commit verification fixes if any were needed**

If a verification command exposed a defect and you edited files to fix it, commit the fix:

```bash
git add <changed-files>
git commit -m "fix: address producer verification issues"
```

If no files changed, do not create a commit.
