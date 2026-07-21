package storage

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestStagePromoteAndIntegrity(t *testing.T) {
	objects, err := NewFilesystem(t.TempDir())
	require.NoError(t, err)
	staged, err := objects.Stage("notes.txt", strings.NewReader("safe UTF-8 text"))
	require.NoError(t, err)
	require.Equal(t, "text/plain", staged.MediaType)
	rejected, err := objects.ScanQuarantine(staged.Key, staged.SHA256, staged.Size)
	require.NoError(t, err)
	require.False(t, rejected)
	require.NoError(t, objects.Promote(staged.Key, staged.SHA256, staged.Size))
	file, err := objects.OpenClean(staged.Key, staged.SHA256, staged.Size)
	require.NoError(t, err)
	require.NoError(t, file.Close())
}

func TestStageRejectsMismatchTraversalAndOversize(t *testing.T) {
	objects, err := NewFilesystem(t.TempDir())
	require.NoError(t, err)
	_, err = objects.Stage("../escape.txt", strings.NewReader("text"))
	require.ErrorIs(t, err, ErrUnsafePath)
	_, err = objects.Stage("image.png", strings.NewReader("not a png"))
	require.ErrorIs(t, err, ErrType)
	_, err = objects.Stage("large.txt", bytes.NewReader(bytes.Repeat([]byte("a"), int(MaxUploadBytes+1))))
	require.ErrorIs(t, err, ErrTooLarge)
}

func TestSymlinkObjectIsRejected(t *testing.T) {
	if os.Getenv("CI_WINDOWS_NO_SYMLINK") != "" {
		t.Skip("symlinks unavailable")
	}
	root := t.TempDir()
	objects, err := NewFilesystem(root)
	require.NoError(t, err)
	key := "00000000-0000-0000-0000-000000000001"
	target := filepath.Join(root, "outside")
	require.NoError(t, os.WriteFile(target, []byte("safe"), 0o600))
	err = os.Symlink(target, filepath.Join(root, "clean", key))
	if errors.Is(err, os.ErrPermission) || os.IsPermission(err) || (runtime.GOOS == "windows" && err != nil) {
		t.Skip("symlinks unavailable")
	}
	require.NoError(t, err)
	_, err = objects.OpenClean(key, "", 0)
	require.ErrorIs(t, err, ErrUnsafePath)
}

func TestEICARFixtureIsRejected(t *testing.T) {
	objects, err := NewFilesystem(t.TempDir())
	require.NoError(t, err)
	fixture := "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
	staged, err := objects.Stage("eicar.txt", strings.NewReader(fixture))
	require.NoError(t, err)
	rejected, err := objects.ScanQuarantine(staged.Key, staged.SHA256, staged.Size)
	if runtime.GOOS == "windows" && err != nil {
		// Microsoft Defender may quarantine the canonical fixture first; this is
		// still a fail-closed result. Linux CI validates the fake scanner verdict.
		require.Error(t, err)
		return
	}
	require.NoError(t, err)
	require.True(t, rejected)
}
