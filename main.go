package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"

	"github.com/joho/godotenv"
)

const (
	redirectURI = "http://127.0.0.1:8080/callback"
	scope       = "user-read-playback-state"
	tokenFile   = "token.json"
	listenAddr  = ":8080"
)

var (
	clientID     string
	clientSecret string
)

type tokenData struct {
	AccessToken  string `json:"access_token"`
	TokenType    string `json:"token_type"`
	Scope        string `json:"scope"`
	ExpiresIn    int    `json:"expires_in"`
	RefreshToken string `json:"refresh_token"`
}

var (
	oauthState  string
	stateMu     sync.Mutex
	storedToken *tokenData
)

func main() {
	loadEnv()
	loadToken()

	http.HandleFunc("/login", loginHandler)
	http.HandleFunc("/callback", callbackHandler(clientSecret))
	http.HandleFunc("/healthz", healthHandler)
	http.HandleFunc("/current-track", getCurrentTrackHandler)
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/login", http.StatusTemporaryRedirect)
	})

	log.Printf("Listening on %s — open http://127.0.0.1%s/login to authenticate", listenAddr, listenAddr)
	log.Fatal(http.ListenAndServe(listenAddr, nil))
}

type trackResponse struct {
	IsPlaying  bool `json:"is_playing"`
	ProgressMs int  `json:"progress_ms"`
	Item       struct {
		Album struct {
			Images []struct {
				URL string `json:"url"`
			} `json:"images"`
		} `json:"album"`
		DurationMs int `json:"duration_ms"`
	} `json:"item"`
}

func getCurrentTrackHandler(w http.ResponseWriter, r *http.Request) {
	token := storedToken.AccessToken
	apiURL := "https://api.spotify.com/v1/me/player"
	req, err := http.NewRequest(http.MethodGet, apiURL, nil)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	// defer resp.Body.Close()
	// body, err := io.ReadAll(resp.Body)
	// if err != nil {
	// 	http.Error(w, err.Error(), http.StatusInternalServerError)
	// 	return
	// }
	// fmt.Println(string(body))
	// w.WriteHeader(http.StatusOK)
	// w.Write(body)
	defer resp.Body.Close()
	var track trackResponse
	if err := json.NewDecoder(resp.Body).Decode(&track); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	fmt.Println(track)
	milliSecondsLeft := track.Item.DurationMs - track.ProgressMs
	fmt.Printf("There are %d seconds left\n", milliSecondsLeft/1000)
	// you can make the picture bigger by splitting the url by the prefix and swaping the encoding for a larger size ie b273 -> 82c1
	http.Redirect(w, r, track.Item.Album.Images[0].URL, 302)
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	state, err := randomState()
	if err != nil {
		http.Error(w, "failed to generate state", http.StatusInternalServerError)
		return
	}

	stateMu.Lock()
	oauthState = state
	stateMu.Unlock()

	params := url.Values{
		"client_id":     {clientID},
		"response_type": {"code"},
		"redirect_uri":  {redirectURI},
		"scope":         {scope},
		"state":         {state},
	}

	authURL := "https://accounts.spotify.com/authorize?" + params.Encode()
	http.Redirect(w, r, authURL, http.StatusTemporaryRedirect)
}

func callbackHandler(clientSecret string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if errMsg := r.URL.Query().Get("error"); errMsg != "" {
			http.Error(w, "spotify authorization denied: "+errMsg, http.StatusBadRequest)
			return
		}

		state := r.URL.Query().Get("state")
		stateMu.Lock()
		expectedState := oauthState
		stateMu.Unlock()

		if state == "" || state != expectedState {
			http.Error(w, "invalid oauth state", http.StatusBadRequest)
			return
		}

		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "missing authorization code", http.StatusBadRequest)
			return
		}

		token, err := exchangeCode(code, clientSecret)
		if err != nil {
			log.Printf("token exchange failed: %v", err)
			http.Error(w, "token exchange failed", http.StatusBadGateway)
			return
		}

		if err := saveToken(token); err != nil {
			log.Printf("failed to save token: %v", err)
			http.Error(w, "failed to save token", http.StatusInternalServerError)
			return
		}

		storedToken = token
		fmt.Fprintf(w, "Spotify authentication successful. Token saved to %s.\n", tokenFile)
		http.Redirect(w, r, "localhost:8080/current-track", http.StatusTemporaryRedirect)
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if storedToken != nil {
		json.NewEncoder(w).Encode(map[string]any{
			"status":     "ok",
			"authorized": true,
		})
		return
	}
	json.NewEncoder(w).Encode(map[string]any{
		"status":     "ok",
		"authorized": false,
	})
}

func exchangeCode(code, clientSecret string) (*tokenData, error) {
	form := url.Values{
		"grant_type":   {"authorization_code"},
		"code":         {code},
		"redirect_uri": {redirectURI},
	}

	req, err := http.NewRequest(http.MethodPost, "https://accounts.spotify.com/api/token", strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Authorization", "Basic "+basicAuth(clientID, clientSecret))

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("spotify returned %s: %s", resp.Status, body)
	}

	var token tokenData
	if err := json.Unmarshal(body, &token); err != nil {
		return nil, err
	}

	return &token, nil
}

func loadEnv() {
	if err := godotenv.Load(); err != nil {
		log.Println("no .env file found, using environment variables")
	}

	clientID = os.Getenv("SPOTIFY_CLIENT_ID")
	clientSecret = os.Getenv("SPOTIFY_CLIENT_SECRET")

	if clientID == "" {
		log.Fatal("SPOTIFY_CLIENT_ID is required")
	}
	if clientSecret == "" {
		log.Fatal("SPOTIFY_CLIENT_SECRET is required")
	}
}

func loadToken() {
	data, err := os.ReadFile(tokenFile)
	if err != nil {
		return
	}

	var token tokenData
	if err := json.Unmarshal(data, &token); err != nil {
		log.Printf("ignoring invalid %s: %v", tokenFile, err)
		return
	}

	storedToken = &token
	log.Printf("loaded existing token from %s", tokenFile)
}

func saveToken(token *tokenData) error {
	data, err := json.MarshalIndent(token, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(tokenFile, data, 0600)
}

func randomState() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

func basicAuth(username, password string) string {
	return base64.StdEncoding.EncodeToString([]byte(username + ":" + password))
}
