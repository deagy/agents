package config

import (
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestDevelopmentAdapterFailsClosed(t *testing.T) {
	base := Config{Mode: "development", Bind: "127.0.0.1:8080", ShutdownTimeout: 10 * time.Second}
	require.NoError(t, base.RequireDevelopmentAdapter())
	unsafe := base
	unsafe.Bind = "0.0.0.0:8080"
	require.Error(t, unsafe.RequireDevelopmentAdapter())
	unsafe.AllowContainerWildcardBind = true
	t.Setenv("SAMPLE001_CONTAINER_RUNTIME", "compose")
	require.NoError(t, unsafe.RequireDevelopmentAdapter())
	t.Setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
	require.Error(t, base.RequireDevelopmentAdapter())
}

func TestModeMustBeExplicit(t *testing.T) {
	cfg := Config{Bind: "127.0.0.1:8080", ShutdownTimeout: 10 * time.Second, DatabaseURL: "postgres://unused"}
	require.ErrorContains(t, cfg.Validate(), "mode must be")
}

func TestScannerFailureDigestIsScannerOnly(t *testing.T) {
	digest := strings.Repeat("a", 64)
	scanner := Config{Service: "scanner-worker", Mode: "development", Bind: "127.0.0.1:8080", HealthBind: "127.0.0.1:9090", DatabaseURL: "postgres://unused", ShutdownTimeout: 10 * time.Second, ScannerFailureSHA256: digest}
	require.NoError(t, scanner.Validate())
	nonScanner := scanner
	nonScanner.Service = "promotion-worker"
	require.ErrorContains(t, nonScanner.Validate(), "scanner-only")
}
