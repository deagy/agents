package bff

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestSecurityHeadersAreSet(t *testing.T) {
	server := &Server{Origin: "http://127.0.0.1:5173"}
	request := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	require.Equal(t, http.StatusOK, response.Code)
	require.Contains(t, response.Header().Get("Content-Security-Policy"), "frame-ancestors 'none'")
	require.Equal(t, "no-referrer", response.Header().Get("Referrer-Policy"))
	require.Equal(t, "nosniff", response.Header().Get("X-Content-Type-Options"))
	require.Equal(t, "DENY", response.Header().Get("X-Frame-Options"))
}
