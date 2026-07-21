package assertion

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"net/http"
	"net/url"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"example.com/sample-001/services/internal/model"
	"example.com/sample-001/services/internal/repository"
)

func TestAssertionBindsMutationAndRejectsReplay(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	require.NoError(t, err)
	now := time.Now().UTC()
	request := &http.Request{Method: http.MethodPost, URL: &url.URL{Path: "/api/v1/documents"}, Header: http.Header{"X-Request-Id": []string{"request-1"}, "Idempotency-Key": []string{"key-1"}}, ContentLength: 100}
	signer := Signer{Issuer: "bff", Audience: "api", KeyID: "key-1", Key: private, Now: func() time.Time { return now }}
	token, err := signer.Sign(request, model.Principal{Tenant: "alpha", Subject: "user", SessionVersion: 1, SessionHash: "session-hash"}, true)
	require.NoError(t, err)
	request.Header.Set(Header, token)
	verifier := Verifier{Issuer: "bff", Audience: "api", KeyID: "key-1", Key: public, Replay: repository.NewMemory(), Now: func() time.Time { return now }}
	principal, err := verifier.Verify(context.Background(), request)
	require.NoError(t, err)
	require.Equal(t, "alpha", principal.Tenant)
	_, err = verifier.Verify(context.Background(), request)
	require.ErrorIs(t, err, ErrInvalid)
}

func TestAssertionRejectsQueryAndBindingTamper(t *testing.T) {
	request := &http.Request{Method: http.MethodGet, URL: &url.URL{Path: "/api/v1/documents/id", RawQuery: "debug=true"}, Header: make(http.Header)}
	require.ErrorIs(t, ValidateRequestShape(request), ErrInvalid)
	request.URL.RawQuery = ""
	request.URL.RawPath = "/api/v1/documents%2fid"
	require.ErrorIs(t, ValidateRequestShape(request), ErrInvalid)
}

func TestAssertionRejectsRequestBindingTampering(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	require.NoError(t, err)
	now := time.Now().UTC()
	base := func() *http.Request {
		return &http.Request{Method: http.MethodPost, URL: &url.URL{Path: "/api/v1/documents"}, Header: http.Header{"X-Request-Id": []string{"request-1"}, "Idempotency-Key": []string{"key-1"}}, ContentLength: 100}
	}
	signer := Signer{Issuer: "bff", Audience: "api", KeyID: "key-1", Key: private, Now: func() time.Time { return now }}
	principal := model.Principal{Tenant: "alpha", Subject: "user", SessionVersion: 3, SessionHash: "session-hash"}
	for name, tamper := range map[string]func(*http.Request){
		"method":          func(r *http.Request) { r.Method = http.MethodDelete },
		"path":            func(r *http.Request) { r.URL.Path += "/other" },
		"request id":      func(r *http.Request) { r.Header.Set("X-Request-ID", "other") },
		"content length":  func(r *http.Request) { r.ContentLength++ },
		"idempotency key": func(r *http.Request) { r.Header.Set("Idempotency-Key", "other") },
	} {
		t.Run(name, func(t *testing.T) {
			request := base()
			token, signErr := signer.Sign(request, principal, true)
			require.NoError(t, signErr)
			request.Header.Set(Header, token)
			tamper(request)
			verifier := Verifier{Issuer: "bff", Audience: "api", KeyID: "key-1", Key: public, Replay: repository.NewMemory(), Now: func() time.Time { return now }}
			_, verifyErr := verifier.Verify(context.Background(), request)
			require.ErrorIs(t, verifyErr, ErrInvalid)
		})
	}
}
