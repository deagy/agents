//go:build windows

package storage

import (
	"os"

	"golang.org/x/sys/windows"
)

func openRegularNoFollow(path string) (*os.File, error) {
	pointer, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	handle, err := windows.CreateFile(pointer, windows.GENERIC_READ, windows.FILE_SHARE_READ, nil, windows.OPEN_EXISTING, windows.FILE_ATTRIBUTE_NORMAL|windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return nil, err
	}
	var info windows.ByHandleFileInformation
	if err = windows.GetFileInformationByHandle(handle, &info); err != nil || info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		_ = windows.CloseHandle(handle)
		return nil, ErrUnsafePath
	}
	file := os.NewFile(uintptr(handle), path)
	stat, statErr := file.Stat()
	if statErr != nil || !stat.Mode().IsRegular() {
		_ = file.Close()
		return nil, ErrUnsafePath
	}
	return file, nil
}
