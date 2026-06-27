package spotify

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

const (
	tokenEndpoint = "https://accounts.spotify.com/api/token"
	expirySkew    = 30 * time.Second
)

var ErrRefreshTokenInvalid = errors.New("spotify refresh token invalid or expired")
var ErrNoToken = errors.New("no spotify token available")

type Token struct {
	AccessToken  string    `json:"access_token"`
	TokenType    string    `json:"token_type"`
	Scope        string    `json:"scope"`
	ExpiresIn    int       `json:"expires_in"`
	RefreshToken string    `json:"refresh_token"`
	ExpiresAt    time.Time `json:"expires_at"`
}

func (t *Token) setExpiryFromNow() {
	if t.ExpiresIn > 0 {
		t.ExpiresAt = time.Now().Add(time.Duration(t.ExpiresIn) * time.Second)
	}
}

func (t *Token) Expired() bool {
	if t.AccessToken == "" || t.ExpiresAt.IsZero() {
		return true
	}
	return time.Now().After(t.ExpiresAt.Add(-expirySkew))
}

type TokenStore interface {
	Load() (*Token, error)
	Save(*Token) error
}

type FileTokenStore struct {
	path string
}

func NewFileTokenStore(path string) *FileTokenStore {
	return &FileTokenStore{path: path}
}

func (s *FileTokenStore) Load() (*Token, error) {
	data, err := os.ReadFile(s.path)
	if err != nil {
		return nil, err
	}

	var token Token
	if err := json.Unmarshal(data, &token); err != nil {
		return nil, err
	}

	if token.ExpiresAt.IsZero() && token.ExpiresIn > 0 {
		info, err := os.Stat(s.path)
		if err == nil {
			token.ExpiresAt = info.ModTime().Add(time.Duration(token.ExpiresIn) * time.Second)
		}
	}

	return &token, nil
}

func (s *FileTokenStore) Save(token *Token) error {
	data, err := json.MarshalIndent(token, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.path, data, 0600)
}

type TokenManager struct {
	cfg   Config
	store TokenStore
	mu    sync.Mutex
}

func NewTokenManager(cfg Config, store TokenStore) *TokenManager {
	return &TokenManager{cfg: cfg, store: store}
}

func (m *TokenManager) Load() (*Token, error) {
	return m.store.Load()
}

func (m *TokenManager) Save(token *Token) error {
	return m.store.Save(token)
}

func (m *TokenManager) Token(ctx context.Context) (*Token, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	token, err := m.store.Load()
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrNoToken, err)
	}

	if !token.Expired() {
		return token, nil
	}

	return m.refreshLocked(ctx, token)
}

func (m *TokenManager) ExchangeCode(ctx context.Context, code string) (*Token, error) {
	form := url.Values{
		"grant_type":   {"authorization_code"},
		"code":         {code},
		"redirect_uri": {m.cfg.RedirectURI},
	}

	token, err := m.requestToken(ctx, form)
	if err != nil {
		return nil, err
	}

	token.setExpiryFromNow()
	if err := m.store.Save(token); err != nil {
		return nil, err
	}

	return token, nil
}

func (m *TokenManager) Refresh(ctx context.Context) (*Token, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	token, err := m.store.Load()
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrNoToken, err)
	}

	return m.refreshLocked(ctx, token)
}

func (m *TokenManager) refreshLocked(ctx context.Context, token *Token) (*Token, error) {
	if token.RefreshToken == "" {
		return nil, ErrRefreshTokenInvalid
	}

	form := url.Values{
		"grant_type":    {"refresh_token"},
		"refresh_token": {token.RefreshToken},
	}

	refreshed, err := m.requestToken(ctx, form)
	if err != nil {
		return nil, err
	}

	if refreshed.RefreshToken == "" {
		refreshed.RefreshToken = token.RefreshToken
	}

	refreshed.setExpiryFromNow()
	if err := m.store.Save(refreshed); err != nil {
		return nil, err
	}

	return refreshed, nil
}

func (m *TokenManager) requestToken(ctx context.Context, form url.Values) (*Token, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, tokenEndpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Authorization", "Basic "+basicAuth(m.cfg.ClientID, m.cfg.ClientSecret))

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
		var errResp struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(body, &errResp)
		if errResp.Error == "invalid_grant" {
			return nil, ErrRefreshTokenInvalid
		}
		return nil, fmt.Errorf("spotify token endpoint returned %s: %s", resp.Status, body)
	}

	var token Token
	if err := json.Unmarshal(body, &token); err != nil {
		return nil, err
	}

	return &token, nil
}

func basicAuth(username, password string) string {
	return base64.StdEncoding.EncodeToString([]byte(username + ":" + password))
}
