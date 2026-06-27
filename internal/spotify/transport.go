package spotify

import (
	"net/http"
)

type authTransport struct {
	base    http.RoundTripper
	manager *TokenManager
}

func newAuthTransport(manager *TokenManager) *authTransport {
	return &authTransport{
		base:    http.DefaultTransport,
		manager: manager,
	}
}

func (t *authTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	resp, err := t.doRequest(req)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode != http.StatusUnauthorized {
		return resp, nil
	}

	resp.Body.Close()

	if _, err = t.manager.Refresh(req.Context()); err != nil {
		return nil, err
	}

	return t.doRequest(req)
}

func (t *authTransport) doRequest(req *http.Request) (*http.Response, error) {
	token, err := t.manager.Token(req.Context())
	if err != nil {
		return nil, err
	}

	cloned := req.Clone(req.Context())
	cloned.Header = req.Header.Clone()
	cloned.Header.Set("Authorization", "Bearer "+token.AccessToken)

	return t.base.RoundTrip(cloned)
}

func NewHTTPClient(manager *TokenManager) *http.Client {
	auth := newAuthTransport(manager)
	return &http.Client{Transport: newRetryTransport(auth)}
}
