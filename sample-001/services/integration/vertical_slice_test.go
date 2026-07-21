package integration_test

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"example.com/sample-001/services/internal/api"
	"example.com/sample-001/services/internal/assertion"
	"example.com/sample-001/services/internal/bff"
	"example.com/sample-001/services/internal/fakeoidc"
	"example.com/sample-001/services/internal/repository"
	"example.com/sample-001/services/internal/session"
	"example.com/sample-001/services/internal/storage"
	"example.com/sample-001/services/internal/worker"
)

func TestRealLocalVerticalSlice(t *testing.T) {
	databaseURL := os.Getenv("SAMPLE001_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("requires migrated disposable PostgreSQL")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	store, err := repository.NewPostgres(ctx, databaseURL)
	require.NoError(t, err)
	defer store.Pool.Close()
	_, err = store.Pool.Exec(ctx, "TRUNCATE consumed_assertions,audit_events,jobs,scan_results,idempotency_keys,documents,sessions RESTART IDENTITY CASCADE")
	require.NoError(t, err)
	objects, err := storage.NewFilesystem(t.TempDir())
	require.NoError(t, err)
	public, private, err := ed25519.GenerateKey(rand.Reader)
	require.NoError(t, err)
	now := time.Now

	apiServer := httptest.NewServer((&api.Server{
		Store: store, Objects: objects, DemoHealth: true,
		Verifier: assertion.Verifier{Issuer: "sample-bff", Audience: "sample-api", KeyID: "dev-1", Key: public, Replay: store, Now: now},
	}).Handler())
	defer apiServer.Close()

	bffServer := httptest.NewUnstartedServer(nil)
	bffURL := "http://" + bffServer.Listener.Addr().String()
	fakeServer := httptest.NewUnstartedServer(nil)
	fakeURL := "http://" + fakeServer.Listener.Addr().String()
	fake, err := fakeoidc.New(fakeURL, "local-client", bffURL+"/auth/callback")
	require.NoError(t, err)
	fakeServer.Config.Handler = fake.Handler()
	fakeServer.Start()
	defer fakeServer.Close()

	sessionKey := make([]byte, 32)
	_, err = rand.Read(sessionKey)
	require.NoError(t, err)
	sessions, err := session.NewStore(store.Pool, sessionKey)
	require.NoError(t, err)
	signer := assertion.Signer{Issuer: "sample-bff", Audience: "sample-api", KeyID: "dev-1", Key: private, Now: now}
	bffHandler, err := bff.New(ctx, sessions, fakeURL, "local-client", "", bffURL+"/auth/callback", apiServer.URL, "http://frontend.invalid", signer, sessionKey)
	require.NoError(t, err)
	bffServer.Config.Handler = bffHandler.Handler()
	bffServer.Start()
	defer bffServer.Close()

	jar, err := cookiejar.New(nil)
	require.NoError(t, err)
	client := &http.Client{Jar: jar, Timeout: 10 * time.Second}
	client.CheckRedirect = func(request *http.Request, _ []*http.Request) error {
		if request.URL.Host == "frontend.invalid" {
			return http.ErrUseLastResponse
		}
		return nil
	}
	response, err := client.Get(bffURL + "/auth/login")
	require.NoError(t, err)
	require.Equal(t, http.StatusFound, response.StatusCode)
	require.NoError(t, response.Body.Close())

	response, err = client.Get(bffURL + "/api/v1/session")
	require.NoError(t, err)
	var current struct {
		Authenticated bool   `json:"authenticated"`
		CSRF          string `json:"csrf_token"`
	}
	require.NoError(t, json.NewDecoder(response.Body).Decode(&current))
	require.NoError(t, response.Body.Close())
	require.True(t, current.Authenticated)
	require.NotEmpty(t, current.CSRF)

	var body bytes.Buffer
	form := multipart.NewWriter(&body)
	part, err := form.CreateFormFile("file", "proof.txt")
	require.NoError(t, err)
	_, err = part.Write([]byte("real vertical slice proof"))
	require.NoError(t, err)
	require.NoError(t, form.Close())
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, bffURL+"/api/v1/documents", bytes.NewReader(body.Bytes()))
	require.NoError(t, err)
	request.Header.Set("Content-Type", form.FormDataContentType())
	request.Header.Set("Origin", "http://frontend.invalid")
	request.Header.Set("X-CSRF-Token", current.CSRF)
	request.Header.Set("Idempotency-Key", "integration-key")
	response, err = client.Do(request)
	require.NoError(t, err)
	require.Equal(t, http.StatusAccepted, response.StatusCode)
	var upload struct {
		Document struct {
			ID string `json:"id"`
		} `json:"document"`
	}
	require.NoError(t, json.NewDecoder(response.Body).Decode(&upload))
	require.NoError(t, response.Body.Close())
	require.NotEmpty(t, upload.Document.ID)
	for _, identity := range [][2]string{{"demo-tenant", "other"}, {"other-tenant", "demo-user"}} {
		_, outsiderSession, createErr := sessions.Create(ctx, identity[0], identity[1], "Outsider", "synthetic-token")
		require.NoError(t, createErr)
		for _, operation := range []struct{ method, suffix string }{{http.MethodGet, ""}, {http.MethodGet, "/content"}, {http.MethodDelete, ""}} {
			outsideRequest, requestErr := http.NewRequestWithContext(ctx, operation.method, apiServer.URL+"/api/v1/documents/"+upload.Document.ID+operation.suffix, nil)
			require.NoError(t, requestErr)
			outsideRequest.Header.Set("X-Request-ID", "isolation-check-"+operation.method+operation.suffix)
			token, signErr := signer.Sign(outsideRequest, outsiderSession.Principal, operation.method == http.MethodDelete)
			require.NoError(t, signErr)
			outsideRequest.Header.Set(assertion.Header, token)
			outsideResponse, requestErr := http.DefaultClient.Do(outsideRequest)
			require.NoError(t, requestErr)
			require.Equal(t, http.StatusNotFound, outsideResponse.StatusCode)
			require.NoError(t, outsideResponse.Body.Close())
		}
	}
	response, err = client.Get(bffURL + "/api/v1/documents/" + upload.Document.ID + "/content")
	require.NoError(t, err)
	require.Equal(t, http.StatusNotFound, response.StatusCode, "quarantined content must not be downloadable")
	require.NoError(t, response.Body.Close())

	wrongStatus, _ := uploadFixture(t, ctx, client, bffURL, "wrong-csrf", "wrong.txt", "blocked", "wrong-token", "http://frontend.invalid")
	require.Equal(t, http.StatusForbidden, wrongStatus)
	wrongOriginStatus, _ := uploadFixture(t, ctx, client, bffURL, "wrong-origin", "wrong-origin.txt", "blocked", current.CSRF, "http://attacker.invalid")
	require.Equal(t, http.StatusForbidden, wrongOriginStatus)

	require.NoError(t, (&worker.Worker{Pool: store.Pool, Objects: objects, Kind: "scan", ScannerVersion: "fake-eicar-v1", PolicyVersion: "demo-v1"}).Run(ctx))
	require.NoError(t, (&worker.Worker{Pool: store.Pool, Objects: objects, Kind: "promotion", PolicyVersion: "demo-v1"}).Run(ctx))
	response, err = client.Get(bffURL + "/api/v1/documents/" + upload.Document.ID + "/content")
	require.NoError(t, err)
	require.Equal(t, http.StatusOK, response.StatusCode)
	content, err := io.ReadAll(response.Body)
	require.NoError(t, err)
	require.NoError(t, response.Body.Close())
	require.Equal(t, "real vertical slice proof", string(content))
	require.Equal(t, "no-store", response.Header.Get("Cache-Control"))
	require.Contains(t, response.Header.Get("Content-Disposition"), "attachment")
	request, err = http.NewRequestWithContext(ctx, http.MethodDelete, bffURL+"/api/v1/documents/"+upload.Document.ID, nil)
	require.NoError(t, err)
	request.Header.Set("Origin", "http://frontend.invalid")
	request.Header.Set("X-CSRF-Token", current.CSRF)
	response, err = client.Do(request)
	require.NoError(t, err)
	require.Equal(t, http.StatusNoContent, response.StatusCode)
	require.NoError(t, response.Body.Close())
	_, err = store.Pool.Exec(ctx, `UPDATE jobs SET status='leased',leased_until=now()-interval '1 second',fencing_token=7 WHERE kind='deletion' AND document_id=$1`, upload.Document.ID)
	require.NoError(t, err)
	require.NoError(t, (&worker.Worker{Pool: store.Pool, Objects: objects, Kind: "deletion", PolicyVersion: "demo-v1"}).Run(ctx))
	response, err = client.Get(bffURL + "/api/v1/documents/" + upload.Document.ID)
	require.NoError(t, err)
	require.Equal(t, http.StatusNotFound, response.StatusCode)
	require.NoError(t, response.Body.Close())

	eicar := "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
	status, rejectedID := uploadFixture(t, ctx, client, bffURL, "eicar-key", "eicar.txt", eicar, current.CSRF, "http://frontend.invalid")
	require.Equal(t, http.StatusAccepted, status)
	require.NoError(t, (&worker.Worker{Pool: store.Pool, Objects: objects, Kind: "scan", ScannerVersion: "fake-eicar-v1", PolicyVersion: "demo-v1"}).Run(ctx))
	var rejectedStatus string
	require.NoError(t, store.Pool.QueryRow(ctx, `SELECT status::text FROM documents WHERE id=$1`, rejectedID).Scan(&rejectedStatus))
	require.Equal(t, "rejected", rejectedStatus)
	response, err = client.Get(bffURL + "/api/v1/documents/" + rejectedID + "/content")
	require.NoError(t, err)
	require.Equal(t, http.StatusNotFound, response.StatusCode, "rejected content must not be downloadable")
	require.NoError(t, response.Body.Close())

	noRedirect := *client
	noRedirect.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err = noRedirect.Get(bffURL + "/auth/login")
	require.NoError(t, err)
	require.Equal(t, http.StatusFound, response.StatusCode)
	require.NoError(t, response.Body.Close())
	response, err = noRedirect.Get(bffURL + "/auth/callback?code=invalid&state=mismatched")
	require.NoError(t, err)
	require.Equal(t, http.StatusBadRequest, response.StatusCode)
	require.NoError(t, response.Body.Close())

	failureContent := "deterministic scanner failure"
	status, failureID := uploadFixture(t, ctx, client, bffURL, "failure-key", "failure.txt", failureContent, current.CSRF, "http://frontend.invalid")
	require.Equal(t, http.StatusAccepted, status)
	digest := sha256.Sum256([]byte(failureContent))
	failureDigest := hex.EncodeToString(digest[:])
	require.NoError(t, (&worker.Worker{Pool: store.Pool, Objects: objects, Kind: "scan", ScannerVersion: "fake-eicar-v1", PolicyVersion: "demo-v1", FailureSHA256: failureDigest}).Run(ctx))
	var failureStatus string
	require.NoError(t, store.Pool.QueryRow(ctx, `SELECT status::text FROM documents WHERE id=$1`, failureID).Scan(&failureStatus))
	require.Equal(t, "pending_scan", failureStatus)
	_, err = store.Pool.Exec(ctx, `UPDATE jobs SET status='leased',leased_until=now()-interval '1 second',available_at=now()-interval '1 second' WHERE kind='scan' AND document_id=$1`, failureID)
	require.NoError(t, err)
	require.NoError(t, (&worker.Worker{Pool: store.Pool, Objects: objects, Kind: "scan", ScannerVersion: "fake-eicar-v1", PolicyVersion: "demo-v1"}).Run(ctx))
	var recoveredStatus, recoveredJob string
	require.NoError(t, store.Pool.QueryRow(ctx, `SELECT d.status::text,j.status::text FROM documents d JOIN jobs j ON j.document_id=d.id AND j.kind='scan' WHERE d.id=$1`, failureID).Scan(&recoveredStatus, &recoveredJob))
	require.Equal(t, "scanning", recoveredStatus)
	require.Equal(t, "complete", recoveredJob)
	require.NoError(t, (&worker.Worker{Pool: store.Pool, Objects: objects, Kind: "promotion", PolicyVersion: "demo-v1"}).Run(ctx))
	require.NoError(t, store.Pool.QueryRow(ctx, `SELECT status::text FROM documents WHERE id=$1`, failureID).Scan(&recoveredStatus))
	require.Equal(t, "clean", recoveredStatus)
}

func uploadFixture(t *testing.T, ctx context.Context, client *http.Client, baseURL, key, name, content, csrf, origin string) (int, string) {
	t.Helper()
	var body bytes.Buffer
	form := multipart.NewWriter(&body)
	part, err := form.CreateFormFile("file", name)
	require.NoError(t, err)
	_, err = part.Write([]byte(content))
	require.NoError(t, err)
	require.NoError(t, form.Close())
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/api/v1/documents", bytes.NewReader(body.Bytes()))
	require.NoError(t, err)
	request.Header.Set("Content-Type", form.FormDataContentType())
	request.Header.Set("Origin", origin)
	request.Header.Set("X-CSRF-Token", csrf)
	request.Header.Set("Idempotency-Key", key)
	response, err := client.Do(request)
	require.NoError(t, err)
	defer func() { _ = response.Body.Close() }()
	var result struct {
		Document struct {
			ID string `json:"id"`
		} `json:"document"`
	}
	if response.StatusCode >= 200 && response.StatusCode < 300 {
		require.NoError(t, json.NewDecoder(response.Body).Decode(&result))
	}
	return response.StatusCode, result.Document.ID
}

func TestDatabaseCapabilityRolesDenyCrossServiceAccess(t *testing.T) {
	databaseURL := os.Getenv("SAMPLE001_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("requires migrated disposable PostgreSQL")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	store, err := repository.NewPostgres(ctx, databaseURL)
	require.NoError(t, err)
	defer store.Pool.Close()
	cases := []struct {
		role, query string
		allowed     bool
	}{
		{"sample001_bff", "SELECT count(*) FROM sessions", true},
		{"sample001_bff", "SELECT count(*) FROM documents", false},
		{"sample001_api", "SELECT count(*) FROM active_sessions", true},
		{"sample001_api", "SELECT count(*) FROM sessions", false},
		{"sample001_scanner", "SELECT count(*) FROM documents", true},
		{"sample001_scanner", "SELECT count(*) FROM sessions", false},
	}
	for _, item := range cases {
		t.Run(item.role+item.query, func(t *testing.T) {
			tx, beginErr := store.Pool.Begin(ctx)
			require.NoError(t, beginErr)
			defer func() { _ = tx.Rollback(ctx) }()
			_, setErr := tx.Exec(ctx, "SET LOCAL ROLE "+item.role)
			require.NoError(t, setErr)
			var count int
			queryErr := tx.QueryRow(ctx, item.query).Scan(&count)
			if item.allowed {
				require.NoError(t, queryErr)
			} else {
				require.Error(t, queryErr)
			}
		})
	}
}
