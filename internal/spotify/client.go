// Package spotify provides a client for the Spotify Web API with OAuth2 support.
package spotify

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

const defaultBaseURL = "https://api.spotify.com/v1"

type Client struct {
	httpClient *http.Client
	baseURL    string
}

func NewClient(manager *TokenManager) *Client {
	return &Client{
		httpClient: NewHTTPClient(manager),
		baseURL:    defaultBaseURL,
	}
}

type PlaybackState struct {
	IsPlaying  bool `json:"is_playing"`
	ProgressMs int  `json:"progress_ms"`
	Item       *struct {
		Album struct {
			Images []struct {
				URL string `json:"url"`
			} `json:"images"`
		} `json:"album"`
		DurationMs int `json:"duration_ms"`
	} `json:"item"`
}

func (c *Client) GetPlaybackState(ctx context.Context) (*PlaybackState, error) {
	var state PlaybackState
	if err := c.Do(ctx, http.MethodGet, "/me/player", nil, &state); err != nil {
		return nil, err
	}
	return &state, nil
}

func (c *Client) Do(ctx context.Context, method, path string, body io.Reader, out any) error {
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, body)
	if err != nil {
		return err
	}

	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNoContent {
		return nil
	}

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("spotify api returned %s: %s", resp.Status, respBody)
	}

	if out == nil {
		return nil
	}

	if err := json.Unmarshal(respBody, out); err != nil {
		return err
	}

	return nil
}
