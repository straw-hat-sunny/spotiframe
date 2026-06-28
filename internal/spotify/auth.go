package spotify

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
)

const authorizeEndpoint = "https://accounts.spotify.com/authorize"

type Auth struct {
	exchanger codeExchanger
	cfg       Config
	state     string
	stateMu   sync.Mutex
}

type codeExchanger interface {
	ExchangeCode(context.Context, string) (*Token, error)
}

func NewAuth(manager *TokenManager) *Auth {
	return newAuth(manager, manager.cfg)
}

func newAuth(exchanger codeExchanger, cfg Config) *Auth {
	return &Auth{exchanger: exchanger, cfg: cfg}
}

func (a *Auth) LoginHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		state, err := randomState()
		if err != nil {
			http.Error(w, "failed to generate state", http.StatusInternalServerError)
			return
		}

		a.stateMu.Lock()
		a.state = state
		a.stateMu.Unlock()

		params := url.Values{
			"client_id":     {a.cfg.ClientID},
			"response_type": {"code"},
			"redirect_uri":  {a.cfg.RedirectURI},
			"scope":         {strings.Join(a.cfg.Scopes, " ")},
			"state":         {state},
		}

		authURL := authorizeEndpoint + "?" + params.Encode()
		http.Redirect(w, r, authURL, http.StatusTemporaryRedirect)
	}
}

func (a *Auth) CallbackHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if errMsg := r.URL.Query().Get("error"); errMsg != "" {
			http.Error(w, "spotify authorization denied: "+errMsg, http.StatusBadRequest)
			return
		}

		state := r.URL.Query().Get("state")
		a.stateMu.Lock()
		expectedState := a.state
		a.stateMu.Unlock()

		if state == "" || state != expectedState {
			http.Error(w, "invalid oauth state", http.StatusBadRequest)
			return
		}

		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "missing authorization code", http.StatusBadRequest)
			return
		}

		_, err := a.exchanger.ExchangeCode(r.Context(), code)
		if err != nil {
			log.Printf("token exchange failed: %v", err)
			http.Error(w, "token exchange failed", http.StatusBadGateway)
			return
		}

		http.Redirect(w, r, "/current-track", http.StatusTemporaryRedirect)
	}
}

func randomState() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}
