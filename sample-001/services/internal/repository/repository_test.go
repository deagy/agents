package repository

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"example.com/sample-001/services/internal/model"
)

func TestMemoryOwnerDocumentQuota(t *testing.T) {
	store := NewMemory()
	owner := model.Principal{Tenant: "alpha", Subject: "owner"}
	for index := 0; index < maxOwnerDocuments; index++ {
		_, _, err := store.ReserveUpload(context.Background(), owner, fmt.Sprintf("key-%d", index), fmt.Sprintf("%064x", index), "doc.txt", "demo-v1")
		require.NoError(t, err)
	}
	_, _, err := store.ReserveUpload(context.Background(), owner, "overflow", fmt.Sprintf("%064x", 999), "doc.txt", "demo-v1")
	require.ErrorIs(t, err, ErrQuota)
	_, _, err = store.ReserveUpload(context.Background(), model.Principal{Tenant: "alpha", Subject: "other"}, "independent", fmt.Sprintf("%064x", 1000), "doc.txt", "demo-v1")
	require.NoError(t, err)
}

func TestOwnerLockSQLAvoidsPostgresNullCharacters(t *testing.T) {
	require.NotContains(t, ownerLockSQL, "chr(0)")
	require.True(t, strings.Contains(ownerLockSQL, "chr(31)"))
}
