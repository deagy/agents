package fakeoidc

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/gorilla/mux"
)

type Server struct {
	Issuer      string
	ClientID    string
	RedirectURI string
	mu          sync.Mutex
	codes       map[string]authorization
	key         ed25519.PrivateKey
	kid         string
	now         func() time.Time
}

type authorization struct {
	Challenge, Nonce, RedirectURI string
	Expires                       time.Time
}

func New(issuer, clientID, redirectURI string) (*Server, error) {
	_, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, err
	}
	return &Server{Issuer: strings.TrimRight(issuer, "/"), ClientID: clientID, RedirectURI: redirectURI, codes: map[string]authorization{}, key: key, kid: uuid.NewString(), now: time.Now}, nil
}

func (s *Server) Handler() http.Handler {
	router := mux.NewRouter()
	router.HandleFunc("/.well-known/openid-configuration", s.discovery).Methods(http.MethodGet)
	router.HandleFunc("/authorize", s.authorize).Methods(http.MethodGet)
	router.HandleFunc("/token", s.token).Methods(http.MethodPost)
	router.HandleFunc("/jwks", s.jwks).Methods(http.MethodGet)
	router.HandleFunc("/logout", s.logout).Methods(http.MethodGet, http.MethodPost)
	router.HandleFunc("/test/rotate", s.rotate).Methods(http.MethodPost)
	router.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "non_production": true})
	}).Methods(http.MethodGet)
	return router
}

func (s *Server) discovery(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"issuer": s.Issuer, "authorization_endpoint": s.Issuer + "/authorize", "token_endpoint": s.Issuer + "/token", "jwks_uri": s.Issuer + "/jwks", "end_session_endpoint": s.Issuer + "/logout", "response_types_supported": []string{"code"}, "subject_types_supported": []string{"public"}, "id_token_signing_alg_values_supported": []string{"EdDSA"}, "code_challenge_methods_supported": []string{"S256"}, "scopes_supported": []string{"openid", "profile"}, "token_endpoint_auth_methods_supported": []string{"client_secret_post", "none"}})
}

func (s *Server) authorize(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	if q.Get("response_type") != "code" || q.Get("client_id") != s.ClientID || q.Get("redirect_uri") != s.RedirectURI || q.Get("code_challenge_method") != "S256" || q.Get("code_challenge") == "" || q.Get("state") == "" || q.Get("nonce") == "" {
		http.Error(w, "invalid authorization request", http.StatusBadRequest)
		return
	}
	code := randomURL(32)
	s.mu.Lock()
	s.codes[code] = authorization{Challenge: q.Get("code_challenge"), Nonce: q.Get("nonce"), RedirectURI: q.Get("redirect_uri"), Expires: s.now().Add(time.Minute)}
	s.mu.Unlock()
	redirect, _ := url.Parse(s.RedirectURI)
	values := redirect.Query()
	values.Set("code", code)
	values.Set("state", q.Get("state"))
	redirect.RawQuery = values.Encode()
	http.Redirect(w, r, redirect.String(), http.StatusFound)
}

func (s *Server) token(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		http.Error(w, "invalid token request", http.StatusBadRequest)
		return
	}
	code := r.Form.Get("code")
	s.mu.Lock()
	auth, ok := s.codes[code]
	if ok {
		delete(s.codes, code)
	}
	s.mu.Unlock()
	verifier := r.Form.Get("code_verifier")
	digest := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(digest[:])
	if !ok || s.now().After(auth.Expires) || r.Form.Get("grant_type") != "authorization_code" || r.Form.Get("client_id") != s.ClientID || r.Form.Get("redirect_uri") != auth.RedirectURI || challenge != auth.Challenge {
		http.Error(w, "invalid_grant", http.StatusBadRequest)
		return
	}
	now := s.now().UTC()
	claims := jwt.MapClaims{"iss": s.Issuer, "aud": s.ClientID, "sub": "demo-user", "tenant": "demo-tenant", "name": "Demo User", "nonce": auth.Nonce, "iat": now.Unix(), "exp": now.Add(5 * time.Minute).Unix()}
	token := jwt.NewWithClaims(jwt.SigningMethodEdDSA, claims)
	token.Header["kid"] = s.kid
	signed, err := token.SignedString(s.key)
	if err != nil {
		http.Error(w, "token error", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"access_token": randomURL(32), "token_type": "Bearer", "expires_in": 300, "id_token": signed, "scope": "openid profile"})
}

func (s *Server) jwks(w http.ResponseWriter, _ *http.Request) {
	s.mu.Lock()
	public := s.key.Public().(ed25519.PublicKey)
	kid := s.kid
	s.mu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"keys": []any{map[string]any{"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig", "kid": kid, "x": base64.RawURLEncoding.EncodeToString(public)}}})
}

func (s *Server) rotate(w http.ResponseWriter, _ *http.Request) {
	_, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		http.Error(w, "rotation failed", http.StatusInternalServerError)
		return
	}
	s.mu.Lock()
	s.key = key
	s.kid = uuid.NewString()
	s.mu.Unlock()
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.URL.Query().Get("post_logout_redirect_uri") != "" {
		http.Error(w, "post-logout redirects are not supported by the local fake", http.StatusBadRequest)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func randomURL(size int) string {
	value := make([]byte, size)
	if _, err := rand.Read(value); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(value)
}
func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

var _ = errors.New
