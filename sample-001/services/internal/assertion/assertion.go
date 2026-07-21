package assertion

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"

	"example.com/sample-001/services/internal/model"
)

const (
	Header = "X-Internal-Assertion"
	maxTTL = 30 * time.Second
	Skew   = 5 * time.Second
)

var ErrInvalid = errors.New("invalid internal assertion")

type Claims struct {
	jwt.RegisteredClaims
	Method          string `json:"method"`
	Path            string `json:"path"`
	RequestID       string `json:"request_id"`
	SessionVersion  int64  `json:"session_version"`
	SessionHash     string `json:"session_hash"`
	Tenant          string `json:"tenant"`
	Subject         string `json:"subject"`
	ContentLength   *int64 `json:"content_length,omitempty"`
	IdempotencyHash string `json:"idempotency_hash,omitempty"`
	DocumentID      string `json:"document_id,omitempty"`
}

type Signer struct {
	Issuer   string
	Audience string
	KeyID    string
	Key      ed25519.PrivateKey
	Now      func() time.Time
}

type Verifier struct {
	Issuer   string
	Audience string
	KeyID    string
	Key      ed25519.PublicKey
	Now      func() time.Time
	Replay   ReplayConsumer
}

type ReplayConsumer interface {
	Consume(ctx context.Context, jti, sessionHash, tenant, subject string, sessionVersion int64, expiresAt time.Time) error
}

func (s Signer) Sign(r *http.Request, principal model.Principal, mutation bool) (string, error) {
	if err := ValidateRequestShape(r); err != nil {
		return "", err
	}
	now := time.Now().UTC()
	if s.Now != nil {
		now = s.Now().UTC()
	}
	claims := Claims{
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer: s.Issuer, Audience: jwt.ClaimStrings{s.Audience},
			IssuedAt: jwt.NewNumericDate(now), NotBefore: jwt.NewNumericDate(now), ExpiresAt: jwt.NewNumericDate(now.Add(maxTTL)),
		},
		Method: r.Method, Path: r.URL.EscapedPath(), RequestID: r.Header.Get("X-Request-ID"),
		SessionVersion: principal.SessionVersion, SessionHash: principal.SessionHash,
		Tenant: principal.Tenant, Subject: principal.Subject,
	}
	if mutation {
		claims.ID = uuid.NewString()
	}
	if r.Method == http.MethodPost && claims.Path == "/api/v1/documents" {
		length := r.ContentLength
		claims.ContentLength = &length
		claims.IdempotencyHash = Hash(r.Header.Get("Idempotency-Key"))
	}
	if r.Method == http.MethodDelete {
		claims.DocumentID = strings.TrimPrefix(claims.Path, "/api/v1/documents/")
	}
	token := jwt.NewWithClaims(jwt.SigningMethodEdDSA, claims)
	token.Header["kid"] = s.KeyID
	return token.SignedString(s.Key)
}

func (v Verifier) Verify(ctx context.Context, r *http.Request) (model.Principal, error) {
	if err := ValidateRequestShape(r); err != nil {
		return model.Principal{}, ErrInvalid
	}
	for _, forbidden := range []string{"X-Tenant-ID", "X-Subject-ID", "X-Session-Version", "X-Authenticated-User"} {
		if r.Header.Get(forbidden) != "" {
			return model.Principal{}, ErrInvalid
		}
	}
	raw := r.Header.Get(Header)
	if raw == "" {
		return model.Principal{}, ErrInvalid
	}
	claims := &Claims{}
	now := time.Now().UTC()
	if v.Now != nil {
		now = v.Now().UTC()
	}
	parser := jwt.NewParser(jwt.WithValidMethods([]string{"EdDSA"}), jwt.WithIssuer(v.Issuer), jwt.WithAudience(v.Audience), jwt.WithLeeway(Skew), jwt.WithExpirationRequired(), jwt.WithIssuedAt(), jwt.WithTimeFunc(func() time.Time { return now }))
	token, err := parser.ParseWithClaims(raw, claims, func(token *jwt.Token) (any, error) {
		if token.Method != jwt.SigningMethodEdDSA || token.Header["alg"] != "EdDSA" || token.Header["kid"] != v.KeyID {
			return nil, ErrInvalid
		}
		return v.Key, nil
	})
	if err != nil || !token.Valid || claims.IssuedAt == nil || claims.NotBefore == nil || claims.ExpiresAt == nil {
		return model.Principal{}, ErrInvalid
	}
	issuedAt := claims.IssuedAt.Time
	notBefore := claims.NotBefore.Time
	if claims.ExpiresAt.Sub(issuedAt) > maxTTL || notBefore.Before(issuedAt.Add(-Skew)) || notBefore.After(issuedAt.Add(Skew)) {
		return model.Principal{}, ErrInvalid
	}
	if claims.Method != r.Method || claims.Path != r.URL.EscapedPath() || claims.RequestID == "" || claims.RequestID != r.Header.Get("X-Request-ID") || claims.Tenant == "" || claims.Subject == "" || claims.SessionHash == "" || claims.SessionVersion < 1 {
		return model.Principal{}, ErrInvalid
	}
	mutation := r.Method == http.MethodPost || r.Method == http.MethodPut || r.Method == http.MethodPatch || r.Method == http.MethodDelete
	if mutation {
		if _, err := uuid.Parse(claims.ID); err != nil || v.Replay == nil {
			return model.Principal{}, ErrInvalid
		}
		if r.Method == http.MethodPost && claims.Path == "/api/v1/documents" {
			if claims.ContentLength == nil || *claims.ContentLength != r.ContentLength || claims.IdempotencyHash == "" || claims.IdempotencyHash != Hash(r.Header.Get("Idempotency-Key")) {
				return model.Principal{}, ErrInvalid
			}
		}
		if r.Method == http.MethodDelete && claims.DocumentID != strings.TrimPrefix(claims.Path, "/api/v1/documents/") {
			return model.Principal{}, ErrInvalid
		}
		if err := v.Replay.Consume(ctx, claims.ID, claims.SessionHash, claims.Tenant, claims.Subject, claims.SessionVersion, claims.ExpiresAt.Time); err != nil {
			return model.Principal{}, ErrInvalid
		}
	}
	return model.Principal{Tenant: claims.Tenant, Subject: claims.Subject, SessionVersion: claims.SessionVersion, SessionHash: claims.SessionHash}, nil
}

func ValidateRequestShape(r *http.Request) error {
	if r.URL.RawQuery != "" || r.URL.ForceQuery || r.URL.Fragment != "" || r.URL.Opaque != "" {
		return ErrInvalid
	}
	escaped := r.URL.EscapedPath()
	lower := strings.ToLower(escaped)
	if escaped == "" || !strings.HasPrefix(escaped, "/") || strings.Contains(escaped, "//") || strings.Contains(escaped, "\\") || strings.Contains(lower, "%2f") || strings.Contains(lower, "%5c") {
		return ErrInvalid
	}
	decoded, err := url.PathUnescape(escaped)
	if err != nil || decoded != r.URL.Path {
		return ErrInvalid
	}
	for _, segment := range strings.Split(decoded, "/") {
		if segment == "." || segment == ".." {
			return ErrInvalid
		}
	}
	return nil
}

func Hash(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func NewDevelopmentKey() (ed25519.PublicKey, ed25519.PrivateKey, error) {
	public, private, err := ed25519.GenerateKey(nil)
	if err != nil {
		return nil, nil, fmt.Errorf("generate development assertion key: %w", err)
	}
	return public, private, nil
}
