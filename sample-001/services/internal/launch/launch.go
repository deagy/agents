package launch

import (
	"context"
	"crypto/ed25519"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"example.com/sample-001/services/internal/api"
	"example.com/sample-001/services/internal/assertion"
	"example.com/sample-001/services/internal/bff"
	"example.com/sample-001/services/internal/config"
	"example.com/sample-001/services/internal/fakeoidc"
	"example.com/sample-001/services/internal/repository"
	"example.com/sample-001/services/internal/session"
	"example.com/sample-001/services/internal/storage"
	"example.com/sample-001/services/internal/worker"
)

func API() error {
	cfg, err := config.Load("document-api")
	if err != nil {
		return err
	}
	if err = cfg.RequireDevelopmentAdapter(); err != nil {
		return err
	}
	if len(cfg.AssertionPublicKey) != ed25519.PublicKeySize {
		return errors.New("32-byte assertion_public_key is required")
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	store, err := repository.NewPostgres(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer store.Pool.Close()
	objects, err := storage.NewFilesystem(cfg.StorageRoot)
	if err != nil {
		return err
	}
	server := &api.Server{Store: store, Objects: objects, Verifier: assertion.Verifier{Issuer: cfg.AssertionIssuer, Audience: cfg.AssertionAudience, KeyID: cfg.AssertionKeyID, Key: ed25519.PublicKey(cfg.AssertionPublicKey), Replay: store}, DemoHealth: true}
	return serve(ctx, cfg.Bind, server.Handler(), cfg.ShutdownTimeout)
}

func BFF() error {
	cfg, err := config.Load("bff")
	if err != nil {
		return err
	}
	if len(cfg.AssertionPrivateKey) != ed25519.PrivateKeySize {
		return errors.New("64-byte assertion_private_key is required")
	}
	if len(cfg.SessionKey) != 32 {
		return errors.New("32-byte session_key is required")
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	store, err := repository.NewPostgres(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer store.Pool.Close()
	sessions, err := session.NewStore(store.Pool, cfg.SessionKey)
	if err != nil {
		return err
	}
	server, err := bff.New(ctx, sessions, cfg.OIDCIssuer, cfg.OIDCClientID, cfg.OIDCClientSecret, cfg.OIDCRedirectURL, cfg.APIURL, cfg.AllowedOrigin, assertion.Signer{Issuer: cfg.AssertionIssuer, Audience: cfg.AssertionAudience, KeyID: cfg.AssertionKeyID, Key: ed25519.PrivateKey(cfg.AssertionPrivateKey)}, cfg.SessionKey)
	if err != nil {
		return err
	}
	return serve(ctx, cfg.Bind, server.Handler(), cfg.ShutdownTimeout)
}

func FakeOIDC() error {
	cfg, err := config.Load("fake-oidc")
	if err != nil {
		return err
	}
	server, err := fakeoidc.New(cfg.OIDCIssuer, cfg.OIDCClientID, cfg.OIDCRedirectURL)
	if err != nil {
		return err
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	return serve(ctx, cfg.Bind, server.Handler(), cfg.ShutdownTimeout)
}

func Worker(kind string) error {
	service := kind + "-worker"
	if kind == "scan" {
		service = "scanner-worker"
	}
	cfg, err := config.Load(service)
	if err != nil {
		return err
	}
	if err = cfg.RequireDevelopmentAdapter(); err != nil {
		return err
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	store, err := repository.NewPostgres(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer store.Pool.Close()
	var objects *storage.Filesystem
	if kind == "scan" {
		objects, err = storage.NewQuarantineReader(cfg.StorageRoot)
	} else {
		objects, err = storage.NewFilesystem(cfg.StorageRoot)
	}
	if err != nil {
		return err
	}
	runner := &worker.Worker{Pool: store.Pool, Objects: objects, Kind: kind, ScannerVersion: "fake-eicar-v1", PolicyVersion: "demo-v1", FailureSHA256: cfg.ScannerFailureSHA256, MaxAttempts: 3}
	healthErrors := workerHealth(ctx, cfg.HealthBind, store)
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		if err := runner.Run(ctx); err != nil {
			slog.Warn("worker iteration failed", "kind", kind, "error_code", "worker_failure")
		}
		select {
		case <-ctx.Done():
			return nil
		case err := <-healthErrors:
			return err
		case <-ticker.C:
		}
	}
}

func workerHealth(ctx context.Context, bind string, store *repository.Postgres) <-chan error {
	result := make(chan error, 1)
	router := http.NewServeMux()
	router.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok","non_production":true}`))
	})
	router.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		check, cancel := context.WithTimeout(r.Context(), time.Second)
		defer cancel()
		if err := store.Pool.Ping(check); err != nil {
			http.Error(w, "not ready", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	})
	server := &http.Server{Addr: bind, Handler: router, ReadHeaderTimeout: 2 * time.Second, IdleTimeout: 30 * time.Second}
	go func() {
		err := server.ListenAndServe()
		if !errors.Is(err, http.ErrServerClosed) {
			result <- err
		}
	}()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	return result
}

func serve(ctx context.Context, bind string, handler http.Handler, timeout time.Duration) error {
	server := &http.Server{Addr: bind, Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 1 << 20}
	result := make(chan error, 1)
	go func() { result <- server.ListenAndServe() }()
	select {
	case err := <-result:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), timeout)
		defer cancel()
		if err := server.Shutdown(shutdown); err != nil {
			return fmt.Errorf("shutdown: %w", err)
		}
		return nil
	}
}
