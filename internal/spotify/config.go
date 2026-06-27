package spotify

type Config struct {
	ClientID     string
	ClientSecret string
	RedirectURI  string
	Scopes       []string
}
