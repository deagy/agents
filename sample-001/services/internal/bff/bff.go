package bff

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"github.com/cenkalti/backoff/v7"
	"github.com/coreos/go-oidc/v3/oidc"
	"github.com/gorilla/mux"
	"golang.org/x/oauth2"

	"example.com/sample-001/services/internal/assertion"
	web "example.com/sample-001/services/internal/httputil"
	"example.com/sample-001/services/internal/session"
)

const sessionCookie = "sample001_session"
const attemptCookie = "sample001_oidc_attempt"

type Server struct {
	Sessions *session.Store
	Provider *oidc.Provider
	Verifier *oidc.IDTokenVerifier
	OAuth    oauth2.Config
	API      *url.URL
	Signer   assertion.Signer
	Origin   string
	AEAD     cipher.AEAD
	Now      func() time.Time
}

type attempt struct {
	State, Nonce, Verifier string
	Expires                time.Time
}

func New(ctx context.Context, sessions *session.Store, issuer, clientID, clientSecret, redirectURL, apiURL, origin string, signer assertion.Signer, cookieKey []byte) (*Server, error) {
	provider, err := backoff.Retry(ctx, func() (*oidc.Provider, error) {
		return oidc.NewProvider(ctx, issuer)
	}, backoff.WithBackOff(backoff.NewExponentialBackOff()), backoff.WithMaxElapsedTime(10*time.Second))
	if err != nil {
		return nil, err
	}
	target, err := url.Parse(apiURL)
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(cookieKey)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	oauth := oauth2.Config{ClientID: clientID, ClientSecret: clientSecret, Endpoint: provider.Endpoint(), RedirectURL: redirectURL, Scopes: []string{oidc.ScopeOpenID, "profile"}}
	return &Server{Sessions: sessions, Provider: provider, Verifier: provider.Verifier(&oidc.Config{ClientID: clientID, SupportedSigningAlgs: []string{"EdDSA"}}), OAuth: oauth, API: target, Signer: signer, Origin: origin, AEAD: aead, Now: time.Now}, nil
}

func (s *Server) Handler() http.Handler {
	r := mux.NewRouter()
	r.HandleFunc("/auth/login", s.login).Methods(http.MethodGet)
	r.HandleFunc("/auth/callback", s.callback).Methods(http.MethodGet)
	r.HandleFunc("/auth/logout", s.logout).Methods(http.MethodPost)
	r.HandleFunc("/api/v1/session", s.currentSession).Methods(http.MethodGet)
	r.PathPrefix("/api/v1/documents").HandlerFunc(s.proxy)
	r.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		web.JSON(w, http.StatusOK, map[string]any{"status": "ok", "non_production": true})
	})
	r.HandleFunc("/readyz", func(w http.ResponseWriter, _ *http.Request) {
		web.JSON(w, http.StatusOK, map[string]any{"status": "ready", "non_production": true})
	})
	return s.requestID(r)
}

func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	state := random(32)
	nonce := random(32)
	verifier := oauth2.GenerateVerifier()
	value, err := s.seal(attempt{State: state, Nonce: nonce, Verifier: verifier, Expires: s.Now().Add(5 * time.Minute)})
	if err != nil {
		web.WriteError(w, r, 500, "auth_unavailable", "authentication is unavailable")
		return
	}
	s.setCookie(w, attemptCookie, value, 5*time.Minute, true)
	challenge := oauth2.S256ChallengeOption(verifier)
	http.Redirect(w, r, s.OAuth.AuthCodeURL(state, oidc.Nonce(nonce), challenge), http.StatusFound)
}

func (s *Server) callback(w http.ResponseWriter, r *http.Request) {
	cookie, err := r.Cookie(attemptCookie)
	if err != nil {
		web.WriteError(w, r, 400, "invalid_callback", "authentication callback is invalid")
		return
	}
	value, err := s.open(cookie.Value)
	if err != nil || value.State != r.URL.Query().Get("state") || s.Now().After(value.Expires) || r.URL.Query().Get("code") == "" {
		web.WriteError(w, r, 400, "invalid_callback", "authentication callback is invalid")
		return
	}
	token, err := s.OAuth.Exchange(r.Context(), r.URL.Query().Get("code"), oauth2.VerifierOption(value.Verifier))
	if err != nil {
		web.WriteError(w, r, 401, "authentication_failed", "authentication failed")
		return
	}
	rawID, _ := token.Extra("id_token").(string)
	idToken, err := s.Verifier.Verify(r.Context(), rawID)
	if err != nil {
		web.WriteError(w, r, 401, "authentication_failed", "authentication failed")
		return
	}
	var claims struct {
		Subject string `json:"sub"`
		Tenant  string `json:"tenant"`
		Name    string `json:"name"`
		Nonce   string `json:"nonce"`
	}
	if err = idToken.Claims(&claims); err != nil || claims.Nonce != value.Nonce || claims.Subject == "" || claims.Tenant == "" {
		web.WriteError(w, r, 401, "authentication_failed", "authentication failed")
		return
	}
	id, created, err := s.Sessions.Create(r.Context(), claims.Tenant, claims.Subject, claims.Name, rawID)
	if err != nil {
		web.WriteError(w, r, 503, "session_unavailable", "session could not be created")
		return
	}
	s.setCookie(w, sessionCookie, id, time.Until(created.AbsoluteExpires), true)
	s.clearCookie(w, attemptCookie)
	http.Redirect(w, r, strings.TrimRight(s.Origin, "/")+"/", http.StatusFound)
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	id, sess, ok := s.authorize(w, r, true, true)
	_ = sess
	if !ok {
		return
	}
	if err := s.Sessions.Revoke(r.Context(), id); err != nil {
		web.WriteError(w, r, 503, "logout_unavailable", "logout could not be completed")
		return
	}
	s.clearCookie(w, sessionCookie)
	w.WriteHeader(http.StatusNoContent)
}
func (s *Server) currentSession(w http.ResponseWriter, r *http.Request) {
	_, sess, ok := s.authorize(w, r, false, false)
	if !ok {
		web.JSON(w, http.StatusOK, map[string]any{"authenticated": false})
		return
	}
	web.JSON(w, http.StatusOK, map[string]any{"authenticated": true, "csrf_token": sess.CSRF, "user": map[string]string{"display_name": sess.DisplayName}})
}

func (s *Server) proxy(w http.ResponseWriter, r *http.Request) {
	mutation := r.Method == http.MethodPost || r.Method == http.MethodDelete
	_, sess, ok := s.authorize(w, r, mutation, true)
	if !ok {
		return
	}
	if err := assertion.ValidateRequestShape(r); err != nil {
		web.WriteError(w, r, 400, "invalid_request", "request target is not canonical")
		return
	}
	proxy := httputil.NewSingleHostReverseProxy(s.API)
	original := proxy.Director
	proxy.Director = func(out *http.Request) {
		original(out)
		for _, h := range []string{assertion.Header, "X-Tenant-ID", "X-Subject-ID", "X-Session-Version", "X-Authenticated-User"} {
			out.Header.Del(h)
		}
		signed, err := s.Signer.Sign(out, sess.Principal, mutation)
		if err != nil {
			out.Header.Set("X-Sample001-Signing-Error", "true")
			return
		}
		out.Header.Set(assertion.Header, signed)
	}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, _ error) {
		web.WriteError(w, r, 502, "api_unavailable", "document service is unavailable")
	}
	proxy.ServeHTTP(w, r)
}

func (s *Server) authorize(w http.ResponseWriter, r *http.Request, mutation, reportFailure bool) (string, session.Session, bool) {
	cookie, err := r.Cookie(sessionCookie)
	if err != nil {
		if reportFailure {
			web.WriteError(w, r, http.StatusUnauthorized, "session_expired", "session has expired")
		}
		return "", session.Session{}, false
	}
	if mutation && (r.Header.Get("Origin") != s.Origin || r.Header.Get("X-CSRF-Token") == "") {
		web.WriteError(w, r, 403, "csrf_failed", "request origin or CSRF token is invalid")
		return "", session.Session{}, false
	}
	sess, err := s.Sessions.Get(r.Context(), cookie.Value, r.Header.Get("X-CSRF-Token"), mutation)
	if err != nil {
		if reportFailure {
			web.WriteError(w, r, 401, "session_expired", "session has expired")
		}
		return "", session.Session{}, false
	}
	return cookie.Value, sess, true
}

func (s *Server) requestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Request-ID") == "" {
			r.Header.Set("X-Request-ID", random(16))
		}
		w.Header().Set("X-Request-ID", r.Header.Get("X-Request-ID"))
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; connect-src 'self' "+s.Origin+"; img-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		next.ServeHTTP(w, r)
	})
}
func (s *Server) seal(value attempt) (string, error) {
	plain, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, s.AEAD.NonceSize())
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(s.AEAD.Seal(nonce, nonce, plain, nil)), nil
}
func (s *Server) open(value string) (attempt, error) {
	raw, err := base64.RawURLEncoding.DecodeString(value)
	if err != nil || len(raw) < s.AEAD.NonceSize() {
		return attempt{}, errors.New("invalid attempt")
	}
	nonce := raw[:s.AEAD.NonceSize()]
	plain, err := s.AEAD.Open(nil, nonce, raw[s.AEAD.NonceSize():], nil)
	if err != nil {
		return attempt{}, err
	}
	var decoded attempt
	if err = json.Unmarshal(plain, &decoded); err != nil {
		return attempt{}, err
	}
	return decoded, nil
}
func (s *Server) setCookie(w http.ResponseWriter, name, value string, duration time.Duration, httpOnly bool) {
	secure := strings.HasPrefix(s.Origin, "https://")
	http.SetCookie(w, &http.Cookie{Name: name, Value: value, Path: "/", HttpOnly: httpOnly, Secure: secure, SameSite: http.SameSiteLaxMode, MaxAge: int(duration.Seconds())})
}
func (s *Server) clearCookie(w http.ResponseWriter, name string) {
	http.SetCookie(w, &http.Cookie{Name: name, Value: "", Path: "/", HttpOnly: true, Secure: strings.HasPrefix(s.Origin, "https://"), SameSite: http.SameSiteLaxMode, MaxAge: -1})
}
func random(size int) string {
	value := make([]byte, size)
	if _, err := rand.Read(value); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(value)
}
