package spotify

import (
	"errors"
	"net/http"
	"strconv"
	"time"
)

const defaultMaxRetries = 3

var ErrRateLimited = errors.New("spotify rate limit exceeded after retries")

// retryTransport retries requests when Spotify returns 429, honoring Retry-After.
// Callers sending POST/PUT bodies must set req.GetBody for retries to succeed.
type retryTransport struct {
	base       http.RoundTripper
	maxRetries int
}

func newRetryTransport(base http.RoundTripper) *retryTransport {
	return &retryTransport{
		base:       base,
		maxRetries: defaultMaxRetries,
	}
}

func (t *retryTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	for attempt := 0; ; attempt++ {
		cloned := req.Clone(req.Context())
		resp, err := t.base.RoundTrip(cloned)
		if err != nil {
			return nil, err
		}

		if resp.StatusCode != http.StatusTooManyRequests {
			return resp, nil
		}

		if attempt >= t.maxRetries {
			return resp, nil
		}

		wait := parseRetryAfter(resp.Header.Get("Retry-After"))
		resp.Body.Close()

		select {
		case <-time.After(wait):
		case <-req.Context().Done():
			return nil, req.Context().Err()
		}
	}
}

func parseRetryAfter(header string) time.Duration {
	if header == "" {
		return time.Second
	}

	if seconds, err := strconv.Atoi(header); err == nil {
		if seconds < 0 {
			return time.Second
		}
		return time.Duration(seconds) * time.Second
	}

	if t, err := http.ParseTime(header); err == nil {
		wait := time.Until(t)
		if wait < 0 {
			return 0
		}
		return wait
	}

	return time.Second
}
