package main

import "testing"

func TestLoadConfigDefaultsToLoopbackForMacDevelopment(t *testing.T) {
	t.Setenv("SPOTIFY_CLIENT_ID", "client-id")
	t.Setenv("SPOTIFY_CLIENT_SECRET", "client-secret")
	t.Setenv("PUBLIC_BASE_URL", "")

	cfg, err := loadConfig()
	if err != nil {
		t.Fatalf("loadConfig() error = %v", err)
	}

	if cfg.PublicBaseURL != "http://127.0.0.1:8080" {
		t.Fatalf("PublicBaseURL = %q, want loopback development URL", cfg.PublicBaseURL)
	}
	if cfg.RedirectURI != "http://127.0.0.1:8080/callback" {
		t.Fatalf("RedirectURI = %q, want loopback callback URL", cfg.RedirectURI)
	}
}

func TestLoadConfigBuildsCallbackFromPublicBaseURL(t *testing.T) {
	t.Setenv("SPOTIFY_CLIENT_ID", "client-id")
	t.Setenv("SPOTIFY_CLIENT_SECRET", "client-secret")
	t.Setenv("PUBLIC_BASE_URL", "https://spotiframe.local/")

	cfg, err := loadConfig()
	if err != nil {
		t.Fatalf("loadConfig() error = %v", err)
	}

	if cfg.PublicBaseURL != "https://spotiframe.local" {
		t.Fatalf("PublicBaseURL = %q, want normalized public URL", cfg.PublicBaseURL)
	}
	if cfg.RedirectURI != "https://spotiframe.local/callback" {
		t.Fatalf("RedirectURI = %q, want public callback URL", cfg.RedirectURI)
	}
}

func TestLoadConfigRejectsPublicBaseURLWithPath(t *testing.T) {
	t.Setenv("SPOTIFY_CLIENT_ID", "client-id")
	t.Setenv("SPOTIFY_CLIENT_SECRET", "client-secret")
	t.Setenv("PUBLIC_BASE_URL", "https://spotiframe.local/app")

	if _, err := loadConfig(); err == nil {
		t.Fatal("loadConfig() error = nil, want invalid PUBLIC_BASE_URL error")
	}
}
