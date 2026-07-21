package api

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"example.com/sample-001/services/internal/assertion"
	"example.com/sample-001/services/internal/model"
	"example.com/sample-001/services/internal/repository"
	"example.com/sample-001/services/internal/storage"
)

func TestUploadAndOwnerIsolation(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	require.NoError(t, err)
	store := repository.NewMemory()
	objects, err := storage.NewFilesystem(t.TempDir())
	require.NoError(t, err)
	now := time.Now().UTC()
	signer := assertion.Signer{Issuer: "bff", Audience: "api", KeyID: "kid", Key: private, Now: func() time.Time { return now }}
	server := (&Server{Store: store, Objects: objects, Verifier: assertion.Verifier{Issuer: "bff", Audience: "api", KeyID: "kid", Key: public, Replay: store, Now: func() time.Time { return now }}, DemoHealth: true}).Handler()
	var body bytes.Buffer
	multipartWriter := multipart.NewWriter(&body)
	part, err := multipartWriter.CreateFormFile("file", "notes.txt")
	require.NoError(t, err)
	_, err = part.Write([]byte("hello secure world"))
	require.NoError(t, err)
	require.NoError(t, multipartWriter.Close())
	request := httptest.NewRequest(http.MethodPost, "http://api/api/v1/documents", bytes.NewReader(body.Bytes()))
	request.Header.Set("Content-Type", multipartWriter.FormDataContentType())
	request.Header.Set("Idempotency-Key", "key-1")
	request.Header.Set("X-Request-ID", "req-1")
	principal := model.Principal{Tenant: "alpha", Subject: "owner", SessionVersion: 1, SessionHash: "owner-session"}
	token, err := signer.Sign(request, principal, true)
	require.NoError(t, err)
	request.Header.Set(assertion.Header, token)
	recorder := httptest.NewRecorder()
	server.ServeHTTP(recorder, request)
	require.Equal(t, http.StatusAccepted, recorder.Code, recorder.Body.String())
	documentID := firstDocumentID(t, recorder.Body.Bytes())
	get := httptest.NewRequest(http.MethodGet, "http://api/api/v1/documents/"+documentID, nil)
	get.Header.Set("X-Request-ID", "req-2")
	other := model.Principal{Tenant: "alpha", Subject: "other", SessionVersion: 1, SessionHash: "other-session"}
	token, err = signer.Sign(get, other, false)
	require.NoError(t, err)
	get.Header.Set(assertion.Header, token)
	recorder = httptest.NewRecorder()
	server.ServeHTTP(recorder, get)
	require.Equal(t, http.StatusNotFound, recorder.Code)
}

func firstDocumentID(t *testing.T, raw []byte) string {
	t.Helper()
	const marker = `"id":"`
	start := bytes.Index(raw, []byte(marker))
	require.GreaterOrEqual(t, start, 0)
	start += len(marker)
	end := bytes.IndexByte(raw[start:], '"')
	require.Greater(t, end, 0)
	return string(raw[start : start+end])
}
