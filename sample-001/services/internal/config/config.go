package config

import (
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/spf13/viper"
)

type Config struct {
	Service              string
	Mode                 string
	Bind                 string
	HealthBind           string
	DatabaseURL          string
	StorageRoot          string
	APIURL               string
	OIDCIssuer           string
	OIDCClientID         string
	OIDCClientSecret     string
	OIDCRedirectURL      string
	AllowedOrigin        string
	AssertionIssuer      string
	AssertionAudience    string
	AssertionKeyID       string
	AssertionPrivateKey  []byte
	AssertionPublicKey   []byte
	SessionKey           []byte
	ScannerFailureSHA256 string
	ShutdownTimeout      time.Duration
}

func Load(service string) (Config, error) {
	v := viper.New()
	v.SetEnvPrefix("SAMPLE001")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()
	v.SetDefault("mode", "")
	v.SetDefault("bind", "127.0.0.1:8080")
	v.SetDefault("health_bind", "127.0.0.1:9090")
	v.SetDefault("storage_root", "./data/objects")
	v.SetDefault("assertion_issuer", "sample-001-bff")
	v.SetDefault("assertion_audience", "sample-001-document-api")
	v.SetDefault("assertion_key_id", "sample-001-dev-1")
	v.SetDefault("shutdown_timeout", "10s")

	privateKey, err := decodeOptional(v.GetString("assertion_private_key"))
	if err != nil {
		return Config{}, fmt.Errorf("assertion private key: %w", err)
	}
	publicKey, err := decodeOptional(v.GetString("assertion_public_key"))
	if err != nil {
		return Config{}, fmt.Errorf("assertion public key: %w", err)
	}
	sessionKey, err := decodeOptional(v.GetString("session_key"))
	if err != nil {
		return Config{}, fmt.Errorf("session key: %w", err)
	}
	cfg := Config{
		Service: service, Mode: strings.ToLower(v.GetString("mode")), Bind: v.GetString("bind"), HealthBind: v.GetString("health_bind"), DatabaseURL: v.GetString("database_url"), StorageRoot: v.GetString("storage_root"), APIURL: v.GetString("api_url"), OIDCIssuer: v.GetString("oidc_issuer"), OIDCClientID: v.GetString("oidc_client_id"), OIDCClientSecret: v.GetString("oidc_client_secret"), OIDCRedirectURL: v.GetString("oidc_redirect_url"), AllowedOrigin: v.GetString("allowed_origin"), AssertionIssuer: v.GetString("assertion_issuer"), AssertionAudience: v.GetString("assertion_audience"), AssertionKeyID: v.GetString("assertion_key_id"), AssertionPrivateKey: privateKey, AssertionPublicKey: publicKey, SessionKey: sessionKey, ScannerFailureSHA256: strings.ToLower(v.GetString("scanner_failure_sha256")), ShutdownTimeout: v.GetDuration("shutdown_timeout"),
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Validate() error {
	if c.Mode != "development" && c.Mode != "test" && c.Mode != "production" {
		return errors.New("mode must be development, test, or production")
	}
	if c.Bind == "" || c.HealthBind == "" || c.ShutdownTimeout <= 0 || c.ShutdownTimeout > time.Minute {
		return errors.New("bind and bounded shutdown timeout are required")
	}
	if c.Service == "fake-oidc" || c.Service == "scanner-worker" {
		if err := c.RequireDevelopmentAdapter(); err != nil {
			return err
		}
	}
	if c.ScannerFailureSHA256 != "" {
		if c.Service != "scanner-worker" || len(c.ScannerFailureSHA256) != 64 {
			return errors.New("scanner_failure_sha256 is a scanner-only 64-character digest")
		}
		if _, err := hex.DecodeString(c.ScannerFailureSHA256); err != nil {
			return errors.New("scanner_failure_sha256 must be hexadecimal")
		}
	}
	if c.Service != "fake-oidc" && c.DatabaseURL == "" {
		return errors.New("database_url is required")
	}
	return nil
}

func (c Config) RequireDevelopmentAdapter() error {
	if c.Mode != "development" && c.Mode != "test" {
		return errors.New("development adapter requires development or test mode")
	}
	if os.Getenv("KUBERNETES_SERVICE_HOST") != "" || strings.EqualFold(os.Getenv("ENVIRONMENT"), "production") || strings.EqualFold(os.Getenv("K8S_ENV"), "production") {
		return errors.New("development adapter refuses Kubernetes or production indicators")
	}
	host, _, err := net.SplitHostPort(c.Bind)
	if err != nil {
		return fmt.Errorf("development adapter bind: %w", err)
	}
	ip := net.ParseIP(host)
	if host != "localhost" && (ip == nil || !ip.IsLoopback()) {
		return errors.New("development adapter must bind to loopback")
	}
	return nil
}

func RequireExactRedirect(raw, expected string) error {
	actualURL, err := url.Parse(raw)
	if err != nil {
		return err
	}
	expectedURL, err := url.Parse(expected)
	if err != nil {
		return err
	}
	if actualURL.String() != expectedURL.String() || actualURL.Fragment != "" || actualURL.User != nil {
		return errors.New("redirect URI is not exactly allowed")
	}
	return nil
}

func decodeOptional(value string) ([]byte, error) {
	if value == "" {
		return nil, nil
	}
	decoded, err := base64.StdEncoding.DecodeString(value)
	if err != nil {
		return nil, errors.New("must be standard base64")
	}
	return decoded, nil
}
