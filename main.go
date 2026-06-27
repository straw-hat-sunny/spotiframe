package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/joho/godotenv"
	"github.com/straw-hat-sunny/spotiframe/internal/spotify"
)

const (
	redirectURI = "http://127.0.0.1:8080/callback"
	tokenFile   = "token.json"
	listenAddr  = ":8080"
)

func main() {
	clientID, clientSecret := loadEnv()

	store := spotify.NewFileTokenStore(tokenFile)
	manager := spotify.NewTokenManager(spotify.Config{
		ClientID:     clientID,
		ClientSecret: clientSecret,
		RedirectURI:  redirectURI,
		Scopes:       []string{"user-read-playback-state"},
	}, store)

	auth := spotify.NewAuth(manager)
	client := spotify.NewClient(manager)

	http.HandleFunc("/login", auth.LoginHandler())
	http.HandleFunc("/callback", auth.CallbackHandler())
	http.HandleFunc("/healthz", healthHandler(store))
	http.HandleFunc("/current-track", getCurrentTrackHandler(client))
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/login", http.StatusTemporaryRedirect)
	})

	log.Printf("Listening on %s — open http://127.0.0.1%s/login to authenticate", listenAddr, listenAddr)
	log.Fatal(http.ListenAndServe(listenAddr, nil))
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

		fmt.Println(track)
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

func loadEnv() (string, string) {
	if err := godotenv.Load(); err != nil {
		log.Println("no .env file found, using environment variables")
	}

	clientID := os.Getenv("SPOTIFY_CLIENT_ID")
	clientSecret := os.Getenv("SPOTIFY_CLIENT_SECRET")

	if clientID == "" {
		log.Fatal("SPOTIFY_CLIENT_ID is required")
	}
	if clientSecret == "" {
		log.Fatal("SPOTIFY_CLIENT_SECRET is required")
	}

	return clientID, clientSecret
}
