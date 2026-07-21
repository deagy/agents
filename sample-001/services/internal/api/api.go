package api

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"

	"github.com/google/uuid"
	"github.com/gorilla/mux"

	"example.com/sample-001/services/internal/assertion"
	web "example.com/sample-001/services/internal/httputil"
	"example.com/sample-001/services/internal/model"
	"example.com/sample-001/services/internal/repository"
	"example.com/sample-001/services/internal/storage"
)

type principalKey struct{}

type Server struct {
	Store       repository.Store
	Objects     *storage.Filesystem
	Verifier    assertion.Verifier
	DemoHealth  bool
	UploadSlots chan struct{}
}

func (s *Server) Handler() http.Handler {
	if s.UploadSlots == nil {
		s.UploadSlots = make(chan struct{}, 4)
	}
	router := mux.NewRouter()
	router.Use(s.requestShape, s.authenticate)
	router.HandleFunc("/api/v1/documents", s.upload).Methods(http.MethodPost)
	router.HandleFunc("/api/v1/documents/{id}", s.get).Methods(http.MethodGet)
	router.HandleFunc("/api/v1/documents/{id}/content", s.download).Methods(http.MethodGet)
	router.HandleFunc("/api/v1/documents/{id}", s.delete).Methods(http.MethodDelete)
	health := mux.NewRouter()
	health.HandleFunc("/healthz", s.health).Methods(http.MethodGet)
	health.HandleFunc("/readyz", s.health).Methods(http.MethodGet)
	health.PathPrefix("/").Handler(router)
	return health
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	web.JSON(w, http.StatusOK, map[string]any{"status": "ok", "non_production": s.DemoHealth})
}

func (s *Server) requestShape(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := assertion.ValidateRequestShape(r); err != nil {
			web.WriteError(w, r, http.StatusBadRequest, "invalid_request", "request target is not canonical")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) authenticate(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		principal, err := s.Verifier.Verify(r.Context(), r)
		if err != nil {
			web.WriteError(w, r, http.StatusUnauthorized, "unauthorized", "request is not authorized")
			return
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), principalKey{}, principal)))
	})
}

func principal(r *http.Request) model.Principal {
	value, _ := r.Context().Value(principalKey{}).(model.Principal)
	return value
}

func (s *Server) upload(w http.ResponseWriter, r *http.Request) {
	select {
	case s.UploadSlots <- struct{}{}:
		defer func() { <-s.UploadSlots }()
	default:
		web.WriteError(w, r, http.StatusTooManyRequests, "upload_busy", "too many uploads are already in progress")
		return
	}
	key := r.Header.Get("Idempotency-Key")
	if key == "" || len(key) > 200 || r.ContentLength < 0 || r.ContentLength > storage.MaxUploadBytes+(64*1024) {
		web.WriteError(w, r, http.StatusBadRequest, "invalid_upload", "a valid multipart upload and idempotency key are required")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, storage.MaxUploadBytes+(64*1024))
	multipart, err := r.MultipartReader()
	if err != nil {
		web.WriteError(w, r, http.StatusBadRequest, "invalid_upload", "multipart form data is required")
		return
	}
	part, err := multipart.NextPart()
	if err != nil || part.FormName() != "file" || part.FileName() == "" {
		web.WriteError(w, r, http.StatusBadRequest, "invalid_upload", "multipart field file is required")
		return
	}
	defer func() { _ = part.Close() }()
	name := part.FileName()
	requestHash := assertion.Hash(fmt.Sprintf("%s\x00%d", name, r.ContentLength))
	document, existing, err := s.Store.ReserveUpload(r.Context(), principal(r), key, requestHash, name, "demo-v1")
	if errors.Is(err, repository.ErrQuota) {
		web.WriteError(w, r, http.StatusTooManyRequests, "quota_exceeded", "the local owner quota has been reached")
		return
	}
	if errors.Is(err, repository.ErrIdempotencyConflict) {
		web.WriteError(w, r, http.StatusConflict, "idempotency_conflict", "idempotency key was already used for a different upload")
		return
	}
	if err != nil {
		web.WriteError(w, r, http.StatusServiceUnavailable, "upload_unavailable", "upload could not be reserved")
		return
	}
	if existing {
		staged, stageErr := s.Objects.Stage(name, part)
		if stageErr != nil {
			web.WriteError(w, r, http.StatusConflict, "idempotency_conflict", "idempotency key was already used for a different upload")
			return
		}
		_ = s.Objects.Delete(staged.Key)
		extra, extraErr := multipart.NextPart()
		if document.Status == "uploading" || document.Name != name || document.Size != staged.Size || document.SHA256 == "" || document.SHA256 != staged.SHA256 || extraErr != io.EOF || extra != nil {
			web.WriteError(w, r, http.StatusConflict, "idempotency_conflict", "idempotency key was already used for a different upload")
			return
		}
		web.JSON(w, http.StatusOK, map[string]any{"document": document})
		return
	}
	staged, err := s.Objects.Stage(name, part)
	if err != nil {
		_ = s.Store.FailUpload(r.Context(), principal(r), document.ID, "validation_failed", web.RequestID(r))
		status, code := http.StatusBadRequest, "invalid_upload"
		if errors.Is(err, storage.ErrTooLarge) {
			status, code = http.StatusRequestEntityTooLarge, "upload_too_large"
		}
		web.WriteError(w, r, status, code, "file was not accepted")
		return
	}
	if extra, extraErr := multipart.NextPart(); extraErr != io.EOF || extra != nil {
		_ = s.Objects.Delete(staged.Key)
		_ = s.Store.FailUpload(r.Context(), principal(r), document.ID, "validation_failed", web.RequestID(r))
		web.WriteError(w, r, http.StatusBadRequest, "invalid_upload", "only one file field is permitted")
		return
	}
	input := model.CreateInput{MediaType: staged.MediaType, Size: staged.Size, SHA256: staged.SHA256, ObjectKey: staged.Key}
	document, err = s.Store.CommitUpload(r.Context(), principal(r), document.ID, input, web.RequestID(r))
	if errors.Is(err, repository.ErrQuota) {
		_ = s.Objects.Delete(staged.Key)
		_ = s.Store.FailUpload(r.Context(), principal(r), document.ID, "quota_exceeded", web.RequestID(r))
		web.WriteError(w, r, http.StatusTooManyRequests, "quota_exceeded", "the local owner quota has been reached")
		return
	}
	if err != nil {
		_ = s.Objects.Delete(staged.Key)
		_ = s.Store.FailUpload(r.Context(), principal(r), document.ID, "commit_failed", web.RequestID(r))
		web.WriteError(w, r, http.StatusServiceUnavailable, "upload_unavailable", "upload could not be committed")
		return
	}
	web.JSON(w, http.StatusAccepted, map[string]any{"document": document})
}

func (s *Server) get(w http.ResponseWriter, r *http.Request) {
	document, err := s.ownerDocument(r)
	if err != nil {
		s.notFound(w, r)
		return
	}
	web.JSON(w, http.StatusOK, map[string]any{"document": document})
}

func (s *Server) download(w http.ResponseWriter, r *http.Request) {
	document, err := s.ownerDocument(r)
	if err != nil || document.Status != "clean" {
		s.notFound(w, r)
		return
	}
	file, err := s.Objects.OpenClean(document.ObjectKey, document.SHA256, document.Size)
	if err != nil {
		web.WriteError(w, r, http.StatusServiceUnavailable, "content_unavailable", "document content is temporarily unavailable")
		return
	}
	defer func() { _ = file.Close() }()
	w.Header().Set("Content-Type", document.MediaType)
	w.Header().Set("Content-Disposition", "attachment; filename*=UTF-8''"+strings.ReplaceAll(url.PathEscape(document.Name), "+", "%20"))
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Length", fmt.Sprint(document.Size))
	w.WriteHeader(http.StatusOK)
	_, _ = io.Copy(w, file)
}

func (s *Server) delete(w http.ResponseWriter, r *http.Request) {
	id := mux.Vars(r)["id"]
	if _, err := uuid.Parse(id); err != nil {
		s.notFound(w, r)
		return
	}
	if err := s.Store.MarkDeleting(r.Context(), principal(r), id, web.RequestID(r)); err != nil {
		s.notFound(w, r)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) ownerDocument(r *http.Request) (model.Document, error) {
	id := mux.Vars(r)["id"]
	if _, err := uuid.Parse(id); err != nil {
		return model.Document{}, repository.ErrNotFound
	}
	return s.Store.Get(r.Context(), principal(r), id)
}

func (s *Server) notFound(w http.ResponseWriter, r *http.Request) {
	web.WriteError(w, r, http.StatusNotFound, "not_found", "document was not found")
}
