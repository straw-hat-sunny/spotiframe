package spotify

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
)

type recordingCodeExchanger struct {
	code string
}

func (e *recordingCodeExchanger) ExchangeCode(_ context.Context, code string) (*Token, error) {
	e.code = code
	return &Token{}, nil
}

func TestCallbackRedirectsRelativeToTheRequestHost(t *testing.T) {
	exchanger := &recordingCodeExchanger{}
	auth := newAuth(exchanger, Config{
		ClientID:    "client-id",
		RedirectURI: "https://spotiframe.local/callback",
		Scopes:      []string{"user-read-playback-state"},
	})

	loginResponse := httptest.NewRecorder()
	auth.LoginHandler().ServeHTTP(loginResponse, httptest.NewRequest(http.MethodGet, "/login", nil))
	loginLocation, err := url.Parse(loginResponse.Header().Get("Location"))
	if err != nil {
		t.Fatalf("parse login redirect: %v", err)
	}
	state := loginLocation.Query().Get("state")
	if state == "" {
		t.Fatal("login redirect did not include OAuth state")
	}

	callbackResponse := httptest.NewRecorder()
	callbackURL := "/callback?code=authorization-code&state=" + url.QueryEscape(state)
	auth.CallbackHandler().ServeHTTP(callbackResponse, httptest.NewRequest(http.MethodGet, callbackURL, nil))

	if callbackResponse.Code != http.StatusTemporaryRedirect {
		t.Fatalf("callback status = %d, want %d", callbackResponse.Code, http.StatusTemporaryRedirect)
	}
	if location := callbackResponse.Header().Get("Location"); location != "/current-track" {
		t.Fatalf("callback Location = %q, want relative redirect", location)
	}
	if exchanger.code != "authorization-code" {
		t.Fatalf("exchanged code = %q, want authorization code", exchanger.code)
	}
}
