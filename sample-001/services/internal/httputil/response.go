package httputil

import (
	"encoding/json"
	"net/http"
)

type Error struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	RequestID string `json:"request_id"`
}

func JSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func WriteError(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	JSON(w, status, Error{Code: code, Message: message, RequestID: RequestID(r)})
}

func RequestID(r *http.Request) string {
	id := r.Header.Get("X-Request-ID")
	if id == "" || len(id) > 128 {
		return "unknown"
	}
	return id
}
