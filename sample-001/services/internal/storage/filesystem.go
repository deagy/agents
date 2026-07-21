package storage

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
)

const MaxUploadBytes int64 = 25 * 1024 * 1024

var (
	ErrTooLarge     = errors.New("upload exceeds 25 MiB")
	ErrType         = errors.New("file type is not permitted")
	ErrUnsafePath   = errors.New("unsafe object path")
	ErrHashMismatch = errors.New("object integrity check failed")
)

type Staged struct {
	Key       string
	Path      string
	Size      int64
	SHA256    string
	MediaType string
}

type Filesystem struct {
	root       string
	quarantine string
	clean      string
}

func NewFilesystem(root string) (*Filesystem, error) {
	absolute, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	for _, dir := range []string{absolute, filepath.Join(absolute, "quarantine"), filepath.Join(absolute, "clean")} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return nil, err
		}
		info, err := os.Lstat(dir)
		if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return nil, ErrUnsafePath
		}
		if runtime.GOOS != "windows" && info.Mode().Perm()&0o077 != 0 {
			if err := os.Chmod(dir, 0o700); err != nil {
				if os.IsPermission(err) && os.Getenv("SAMPLE001_ALLOW_RELAXED_STORAGE_PERMISSIONS") == "true" {
					continue
				}
				return nil, err
			}
		}
	}
	return &Filesystem{root: absolute, quarantine: filepath.Join(absolute, "quarantine"), clean: filepath.Join(absolute, "clean")}, nil
}

func NewQuarantineReader(root string) (*Filesystem, error) {
	absolute, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	quarantine := filepath.Join(absolute, "quarantine")
	for _, dir := range []string{absolute, quarantine} {
		info, err := os.Lstat(dir)
		if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return nil, ErrUnsafePath
		}
	}
	return &Filesystem{root: absolute, quarantine: quarantine, clean: filepath.Join(absolute, "clean")}, nil
}

func (f *Filesystem) Stage(name string, src io.Reader) (staged Staged, err error) {
	key := uuid.NewString()
	if err := validateName(name); err != nil {
		return Staged{}, err
	}
	tmp, err := f.createExclusiveTemp(key)
	if err != nil {
		return Staged{}, err
	}
	tmpName := tmp.Name()
	defer func() {
		_ = tmp.Close()
		if err != nil {
			_ = os.Remove(tmpName)
		}
	}()

	hash := sha256.New()
	limited := &io.LimitedReader{R: src, N: MaxUploadBytes + 1}
	probe := make([]byte, 512)
	n, readErr := io.ReadFull(limited, probe)
	if readErr != nil && readErr != io.EOF && readErr != io.ErrUnexpectedEOF {
		return Staged{}, readErr
	}
	probe = probe[:n]
	mediaType, err := acceptedType(name, probe)
	if err != nil {
		return Staged{}, err
	}
	validator := newUTF8Validator(mediaType == "text/plain")
	writer := io.MultiWriter(tmp, hash, validator)
	written, err := writer.Write(probe)
	if err != nil || written != len(probe) {
		return Staged{}, errors.Join(err, io.ErrShortWrite)
	}
	rest, err := io.Copy(writer, limited)
	if err != nil {
		return Staged{}, err
	}
	size := int64(n) + rest
	if size > MaxUploadBytes {
		return Staged{}, ErrTooLarge
	}
	if err := validator.Finalize(); err != nil {
		return Staged{}, err
	}
	if err := tmp.Sync(); err != nil {
		return Staged{}, err
	}
	if err := tmp.Close(); err != nil {
		return Staged{}, err
	}
	destination, err := f.safeObjectPath(f.quarantine, key)
	if err != nil {
		return Staged{}, err
	}
	if _, statErr := os.Lstat(destination); statErr == nil {
		return Staged{}, os.ErrExist
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return Staged{}, statErr
	}
	if err := os.Rename(tmpName, destination); err != nil {
		return Staged{}, err
	}
	if err := syncDir(f.quarantine); err != nil {
		_ = os.Remove(destination)
		return Staged{}, err
	}
	return Staged{Key: key, Path: destination, Size: size, SHA256: hex.EncodeToString(hash.Sum(nil)), MediaType: mediaType}, nil
}

func (f *Filesystem) OpenClean(key, expectedHash string, expectedSize int64) (*os.File, error) {
	path, err := f.safeObjectPath(f.clean, key)
	if err != nil {
		return nil, err
	}
	file, err := openRegularNoFollow(path)
	if err != nil {
		return nil, err
	}
	hash := sha256.New()
	size, err := io.Copy(hash, file)
	if err != nil || size != expectedSize || !strings.EqualFold(hex.EncodeToString(hash.Sum(nil)), expectedHash) {
		_ = file.Close()
		return nil, ErrHashMismatch
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		_ = file.Close()
		return nil, err
	}
	return file, nil
}

func (f *Filesystem) ScanQuarantine(key, expectedHash string, expectedSize int64) (bool, error) {
	path, err := f.safeObjectPath(f.quarantine, key)
	if err != nil {
		return false, err
	}
	file, err := openRegularNoFollow(path)
	if err != nil {
		return false, err
	}
	defer func() { _ = file.Close() }()
	hash := sha256.New()
	const eicar = "EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
	buffer := make([]byte, 32*1024)
	tail := ""
	var size int64
	rejected := false
	for {
		n, readErr := file.Read(buffer)
		if n > 0 {
			size += int64(n)
			_, _ = hash.Write(buffer[:n])
			sample := tail + string(buffer[:n])
			if strings.Contains(sample, eicar) {
				rejected = true
			}
			if len(sample) > len(eicar) {
				tail = sample[len(sample)-len(eicar):]
			} else {
				tail = sample
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return false, readErr
		}
	}
	if size != expectedSize || !strings.EqualFold(hex.EncodeToString(hash.Sum(nil)), expectedHash) {
		return false, ErrHashMismatch
	}
	return rejected, nil
}

func (f *Filesystem) Promote(key, expectedHash string, expectedSize int64) error {
	source, err := f.safeObjectPath(f.quarantine, key)
	if err != nil {
		return err
	}
	file, err := openRegularNoFollow(source)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			existing, openErr := f.OpenClean(key, expectedHash, expectedSize)
			if openErr == nil {
				return existing.Close()
			}
		}
		return err
	}
	hash := sha256.New()
	size, copyErr := io.Copy(hash, file)
	closeErr := file.Close()
	if copyErr != nil || closeErr != nil || size != expectedSize || !strings.EqualFold(hex.EncodeToString(hash.Sum(nil)), expectedHash) {
		return ErrHashMismatch
	}
	destination, err := f.safeObjectPath(f.clean, key)
	if err != nil {
		return err
	}
	if err := os.Rename(source, destination); err != nil {
		return err
	}
	return syncDir(f.clean)
}

func (f *Filesystem) Delete(key string) error {
	for _, dir := range []string{f.quarantine, f.clean} {
		path, err := f.safeObjectPath(dir, key)
		if err != nil {
			return err
		}
		if info, err := os.Lstat(path); err == nil {
			if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
				return ErrUnsafePath
			}
			if err := os.Remove(path); err != nil {
				return err
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
	return nil
}

func (f *Filesystem) createExclusiveTemp(key string) (*os.File, error) {
	random := make([]byte, 16)
	if _, err := rand.Read(random); err != nil {
		return nil, err
	}
	path := filepath.Join(f.quarantine, "."+key+"."+hex.EncodeToString(random)+".tmp")
	return os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
}

func (f *Filesystem) safeObjectPath(dir, key string) (string, error) {
	parsed, err := uuid.Parse(key)
	if err != nil || parsed.String() != strings.ToLower(key) {
		return "", ErrUnsafePath
	}
	candidate := filepath.Clean(filepath.Join(dir, key))
	relative, err := filepath.Rel(dir, candidate)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || filepath.IsAbs(relative) {
		return "", ErrUnsafePath
	}
	return candidate, nil
}

func validateName(name string) error {
	if name == "" || len(name) > 255 || name != filepath.Base(name) || strings.ContainsAny(name, "\x00/\\") || !utf8.ValidString(name) {
		return ErrUnsafePath
	}
	return nil
}

func acceptedType(name string, probe []byte) (string, error) {
	ext := strings.ToLower(filepath.Ext(name))
	detected := http.DetectContentType(probe)
	detected, _, _ = mime.ParseMediaType(detected)
	allowed := map[string][]string{
		".pdf":  {"application/pdf"},
		".png":  {"image/png"},
		".jpg":  {"image/jpeg"},
		".jpeg": {"image/jpeg"},
		".txt":  {"text/plain"},
	}
	for _, expected := range allowed[ext] {
		if detected == expected || (expected == "text/plain" && detected == "application/octet-stream" && utf8.Valid(probe)) {
			return expected, nil
		}
	}
	return "", fmt.Errorf("%w: extension %q does not match detected type %q", ErrType, ext, detected)
}

func syncDir(path string) error {
	if runtime.GOOS == "windows" {
		return nil
	}
	dir, err := os.Open(path)
	if err != nil {
		return err
	}
	defer func() { _ = dir.Close() }()
	return dir.Sync()
}

type utf8Validator struct {
	enabled bool
	tail    []byte
	invalid bool
}

func newUTF8Validator(enabled bool) *utf8Validator { return &utf8Validator{enabled: enabled} }

func (v *utf8Validator) Write(p []byte) (int, error) {
	if !v.enabled {
		return len(p), nil
	}
	data := append(append([]byte(nil), v.tail...), p...)
	v.tail = v.tail[:0]
	for len(data) > 0 {
		if !utf8.FullRune(data) {
			v.tail = append(v.tail, data...)
			break
		}
		_, size := utf8.DecodeRune(data)
		if size == 1 && data[0] >= utf8.RuneSelf {
			v.invalid = true
		}
		data = data[size:]
	}
	return len(p), nil
}

func (v *utf8Validator) Finalize() error {
	if v.enabled && (v.invalid || len(v.tail) != 0) {
		return ErrType
	}
	return nil
}
