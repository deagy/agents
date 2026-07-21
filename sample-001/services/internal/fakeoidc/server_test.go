package fakeoidc

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestLogoutRejectsCallerControlledRedirect(t *testing.T) {
	server, err := New("http://127.0.0.1:8086", "client", "http://127.0.0.1:8080/auth/callback")
	require.NoError(t, err)
	request := httptest.NewRequest(http.MethodGet, "/logout?post_logout_redirect_uri=https://attacker.invalid", nil)
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	require.Equal(t, http.StatusBadRequest, response.Code)
	require.Empty(t, response.Header().Get("Location"))
}
