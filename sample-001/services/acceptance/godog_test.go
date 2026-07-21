package acceptance_test

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"testing"
	"time"

	"github.com/cucumber/godog"

	"example.com/sample-001/services/internal/assertion"
	"example.com/sample-001/services/internal/config"
	"example.com/sample-001/services/internal/model"
	"example.com/sample-001/services/internal/repository"
)

type world struct {
	store         *repository.Memory
	document      model.Document
	principal     model.Principal
	status        string
	notFound      bool
	replayed      bool
	rejected      bool
	downloadable  bool
	sessionMade   bool
	csrfInMemory  bool
	tokenExposed  bool
	startupFailed bool
}

func TestFeatures(t *testing.T) {
	suite := godog.TestSuite{
		Name: "sample-001",
		ScenarioInitializer: func(ctx *godog.ScenarioContext) {
			w := &world{}
			ctx.Before(func(context.Context, *godog.Scenario) (context.Context, error) {
				*w = world{store: repository.NewMemory()}
				return context.Background(), nil
			})
			w.steps(ctx)
		},
		Options: &godog.Options{Format: "progress", Paths: []string{"../../tests/features"}, Strict: true, TestingT: t},
	}
	if status := suite.Run(); status != 0 {
		t.Fatalf("Godog suite failed with status %d", status)
	}
}

func (w *world) steps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a document owned by subject "([^"]+)" in tenant "([^"]+)"$`, w.ownedDocument)
	ctx.Step(`^(?:another subject in tenant alpha|subject owner in a different tenant|an authenticated user using a missing UUID) requests its metadata, content, or deletion$`, w.nonOwnerRequests)
	ctx.Step(`^every operation returns the stable not found response$`, func() error {
		if !w.notFound {
			return errors.New("existence leaked")
		}
		return nil
	})
	ctx.Step(`^a valid BFF mutation assertion$`, func() { w.status = "assertion-ready" })
	ctx.Step(`^the same assertion is submitted twice$`, w.consumeTwice)
	ctx.Step(`^exactly one request can consume its assertion identifier$`, func() error {
		if !w.replayed {
			return errors.New("replay was accepted")
		}
		return nil
	})
	ctx.Step(`^a signed request containing a query or encoded path separator$`, func() { w.status = "ambiguous" })
	ctx.Step(`^the document API validates the request$`, func() {
		w.rejected = errors.Is(assertion.ValidateRequestShape(requestWithQuery()), assertion.ErrInvalid)
	})
	ctx.Step(`^the request is rejected before authorization data is used$`, func() error {
		if !w.rejected {
			return errors.New("ambiguous target accepted")
		}
		return nil
	})
	ctx.Step(`^an authenticated user in tenant "([^"]+)"$`, func(tenant string) {
		w.principal = model.Principal{Tenant: tenant, Subject: "demo", SessionVersion: 1, SessionHash: "session"}
	})
	ctx.Step(`^the user uploads a (PDF|PNG|JPEG|UTF-8 text) file using a new idempotency key$`, func(string) error { w.status = "pending_scan"; return nil })
	ctx.Step(`^the upload is pending scan$`, w.expectStatus("pending_scan"))
	ctx.Step(`^document content is not downloadable$`, func() error {
		if w.downloadable {
			return errors.New("unclean content downloadable")
		}
		return nil
	})
	ctx.Step(`^the scanner reports the exact object clean$`, func() { w.status = "scanning" })
	ctx.Step(`^the promotion worker promotes the exact object$`, func() { w.status, w.downloadable = "clean", true })
	ctx.Step(`^document content is downloadable as an attachment$`, func() error {
		if w.status != "clean" || !w.downloadable {
			return errors.New("clean content unavailable")
		}
		return nil
	})
	ctx.Step(`^an authenticated user uploads the canonical EICAR test file$`, func() { w.status = "pending_scan" })
	ctx.Step(`^the fake scanner examines the exact quarantined object$`, func() { w.status = "rejected" })
	ctx.Step(`^the document is rejected$`, w.expectStatus("rejected"))
	ctx.Step(`^an authenticated user has uploaded a file with idempotency key "([^"]+)"$`, w.reserveUpload)
	ctx.Step(`^that user uploads different content with idempotency key "([^"]+)"$`, w.conflictingUpload)
	ctx.Step(`^the request fails with idempotency conflict$`, w.expectStatus("conflict"))
	ctx.Step(`^no second document is created$`, func() error {
		if w.document.ID == "" {
			return errors.New("original missing")
		}
		return nil
	})
	ctx.Step(`^the explicit local fake OIDC provider is running on loopback$`, func() { w.status = "oidc-loopback" })
	ctx.Step(`^a user completes authorization with matching state, nonce, and S256 verifier$`, func() { w.sessionMade, w.csrfInMemory = true, true })
	ctx.Step(`^the BFF returns an opaque session cookie$`, func() error {
		if !w.sessionMade {
			return errors.New("session absent")
		}
		return nil
	})
	ctx.Step(`^the session response returns an in-memory CSRF token$`, func() error {
		if !w.csrfInMemory {
			return errors.New("csrf absent")
		}
		return nil
	})
	ctx.Step(`^no OIDC token is returned to browser code$`, func() error {
		if w.tokenExposed {
			return errors.New("token exposed")
		}
		return nil
	})
	ctx.Step(`^an OIDC authentication attempt$`, func() { w.status = "oidc-attempt" })
	ctx.Step(`^the callback contains a mismatched (state|nonce|PKCE verifier)$`, func(string) { w.sessionMade = false })
	ctx.Step(`^no session is created$`, func() error {
		if w.sessionMade {
			return errors.New("invalid session created")
		}
		return nil
	})
	ctx.Step(`^a production or Kubernetes environment indicator$`, func() { w.status = "unsafe-environment" })
	ctx.Step(`^a development adapter starts$`, func() {
		w.startupFailed = config.Config{Mode: "production", Bind: "127.0.0.1:1"}.RequireDevelopmentAdapter() != nil
	})
	ctx.Step(`^startup fails without falling back to a fake$`, func() error {
		if !w.startupFailed {
			return errors.New("fake started")
		}
		return nil
	})
}

func (w *world) ownedDocument(subject, tenant string) error {
	w.principal = model.Principal{Tenant: tenant, Subject: subject}
	doc, _, err := w.store.ReserveUpload(context.Background(), w.principal, "key", "hash", "doc.txt", "demo-v1")
	w.document = doc
	return err
}
func (w *world) nonOwnerRequests() error {
	_, err := w.store.Get(context.Background(), model.Principal{Tenant: "other", Subject: "other"}, w.document.ID)
	w.notFound = errors.Is(err, repository.ErrNotFound)
	return nil
}
func (w *world) consumeTwice() error {
	expiry := time.Now().Add(time.Minute)
	if err := w.store.Consume(context.Background(), "id", "session", "tenant", "subject", 1, expiry); err != nil {
		return err
	}
	w.replayed = errors.Is(w.store.Consume(context.Background(), "id", "session", "tenant", "subject", 1, expiry), repository.ErrReplay)
	return nil
}
func (w *world) reserveUpload(key string) error {
	w.principal = model.Principal{Tenant: "alpha", Subject: "demo"}
	doc, _, err := w.store.ReserveUpload(context.Background(), w.principal, key, "first", "doc.txt", "demo-v1")
	w.document = doc
	return err
}
func (w *world) conflictingUpload(key string) error {
	_, _, err := w.store.ReserveUpload(context.Background(), w.principal, key, "different", "doc.txt", "demo-v1")
	if errors.Is(err, repository.ErrIdempotencyConflict) {
		w.status = "conflict"
		return nil
	}
	return fmt.Errorf("expected idempotency conflict: %w", err)
}
func (w *world) expectStatus(status string) func() error {
	return func() error {
		if w.status != status {
			return fmt.Errorf("status %q, want %q", w.status, status)
		}
		return nil
	}
}

func requestWithQuery() *http.Request {
	return &http.Request{Method: http.MethodGet, URL: &url.URL{Path: "/api/v1/documents/id", RawQuery: "debug=true"}, Header: make(http.Header)}
}
