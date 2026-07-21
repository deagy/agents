//go:build !windows

package storage

import (
	"os"

	"golang.org/x/sys/unix"
)

func openRegularNoFollow(path string) (*os.File, error) {
	fd, err := unix.Open(path, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(fd), path)
	stat, statErr := file.Stat()
	if statErr != nil || !stat.Mode().IsRegular() {
		_ = file.Close()
		return nil, ErrUnsafePath
	}
	return file, nil
}
