package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/joho/godotenv"
	"github.com/straw-hat-sunny/spotiframe/internal/spotify"
)

const (
	tokenFile            = "token.json"
	defaultListenAddr    = "127.0.0.1:8080"
	defaultPublicBaseURL = "http://127.0.0.1:8080"
)

type appConfig struct {
	ClientID      string
	ClientSecret  string
	PublicBaseURL string
	RedirectURI   string
	ListenAddr    string
}

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatal(err)
	}

	store := spotify.NewFileTokenStore(tokenFile)
	spotifyCfg := spotify.Config{
		ClientID:     cfg.ClientID,
		ClientSecret: cfg.ClientSecret,
		RedirectURI:  cfg.RedirectURI,
		Scopes:       []string{"user-read-playback-state"},
	}
	manager := spotify.NewTokenManager(spotifyCfg, store)

	auth := spotify.NewAuth(manager)
	client := spotify.NewClient(manager)

	mux := http.NewServeMux()
	mux.HandleFunc("/login", auth.LoginHandler())
	mux.HandleFunc("/callback", auth.CallbackHandler())
	mux.HandleFunc("/healthz", healthHandler(store))
	mux.HandleFunc("/current-track", getCurrentTrackHandler(client))
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/login", http.StatusTemporaryRedirect)
	})

	server := &http.Server{Addr: cfg.ListenAddr, Handler: mux}
	serverErr := make(chan error, 1)
	go func() {
		log.Printf("Starting web server at %s (public URL: %s)", cfg.ListenAddr, cfg.PublicBaseURL)
		serverErr <- server.ListenAndServe()
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(sig)

	select {
	case <-sig:
		log.Println("Shutting down safely...")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			log.Printf("Web server shutdown failed: %v", err)
		}
	case err := <-serverErr:
		if !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("Web server failed: %v", err)
		}
	}
}

func getCurrentTrackHandler(client *spotify.Client) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		track, err := client.GetPlaybackState(r.Context())
		if err != nil {
			if errors.Is(err, spotify.ErrNoToken) || errors.Is(err, spotify.ErrRefreshTokenInvalid) {
				http.Error(w, "not authenticated — visit /login", http.StatusUnauthorized)
				return
			}
			http.Error(w, err.Error(), http.StatusBadGateway)
			return
		}

		//fmt.Println(track)
		if track.Item == nil || len(track.Item.Album.Images) == 0 {
			http.Error(w, "no track currently playing", http.StatusNotFound)
			return
		}

		milliSecondsLeft := track.Item.DurationMs - track.ProgressMs
		fmt.Printf("There are %d seconds left\n", milliSecondsLeft/1000)
		http.Redirect(w, r, track.Item.Album.Images[0].URL, http.StatusFound)
	}
}

func healthHandler(store spotify.TokenStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		token, err := store.Load()
		authorized := err == nil && token.RefreshToken != ""

		json.NewEncoder(w).Encode(map[string]any{
			"status":     "ok",
			"authorized": authorized,
		})
	}
}

func loadConfig() (appConfig, error) {
	if err := godotenv.Load(); err != nil {
		log.Println("no .env file found, using environment variables")
	}

	clientID := os.Getenv("SPOTIFY_CLIENT_ID")
	clientSecret := os.Getenv("SPOTIFY_CLIENT_SECRET")

	if clientID == "" {
		return appConfig{}, errors.New("SPOTIFY_CLIENT_ID is required")
	}
	if clientSecret == "" {
		return appConfig{}, errors.New("SPOTIFY_CLIENT_SECRET is required")
	}

	publicBaseURL := strings.TrimSpace(os.Getenv("PUBLIC_BASE_URL"))
	if publicBaseURL == "" {
		publicBaseURL = defaultPublicBaseURL
	}

	parsedURL, err := url.Parse(publicBaseURL)
	if err != nil || parsedURL.Host == "" || (parsedURL.Scheme != "http" && parsedURL.Scheme != "https") {
		return appConfig{}, fmt.Errorf("PUBLIC_BASE_URL must be an absolute HTTP(S) URL: %q", publicBaseURL)
	}
	if parsedURL.User != nil || (parsedURL.Path != "" && parsedURL.Path != "/") || parsedURL.RawQuery != "" || parsedURL.Fragment != "" {
		return appConfig{}, fmt.Errorf("PUBLIC_BASE_URL must not contain credentials, a path, query, or fragment: %q", publicBaseURL)
	}

	publicBaseURL = strings.TrimSuffix(publicBaseURL, "/")
	listenAddr := strings.TrimSpace(os.Getenv("LISTEN_ADDR"))
	if listenAddr == "" {
		listenAddr = defaultListenAddr
	}

	return appConfig{
		ClientID:      clientID,
		ClientSecret:  clientSecret,
		PublicBaseURL: publicBaseURL,
		RedirectURI:   publicBaseURL + "/callback",
		ListenAddr:    listenAddr,
	}, nil
}
