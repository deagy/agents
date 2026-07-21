package worker

import (
	"context"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestScannerFailureInjectionMatchesExactDigest(t *testing.T) {
	digest := strings.Repeat("a", 64)
	runner := &Worker{FailureSHA256: digest}
	err := runner.scan(context.Background(), job{SHA256: digest})
	require.ErrorContains(t, err, "injected scanner failure")
}
