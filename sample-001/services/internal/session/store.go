package session

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/sample-001/services/internal/model"
)

var ErrInvalid = errors.New("session is invalid or expired")

type Session struct {
	Principal         model.Principal
	DisplayName, CSRF string
	AbsoluteExpires   time.Time
}
type Store struct {
	Pool *pgxpool.Pool
	AEAD cipher.AEAD
	Now  func() time.Time
}

func NewStore(pool *pgxpool.Pool, key []byte) (*Store, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return &Store{Pool: pool, AEAD: aead, Now: time.Now}, nil
}

func (s *Store) Create(ctx context.Context, tenant, subject, displayName, rawToken string) (string, Session, error) {
	id := random(32)
	csrf := random(32)
	now := s.Now().UTC()
	absolute := now.Add(8 * time.Hour)
	ciphertext, err := s.seal([]byte(rawToken))
	if err != nil {
		return "", Session{}, err
	}
	csrfCiphertext, err := s.seal([]byte(csrf))
	if err != nil {
		return "", Session{}, err
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	_, err = s.Pool.Exec(ctx, `INSERT INTO sessions(id_hash,tenant_id,subject_id,display_name,token_ciphertext,csrf_hash,csrf_ciphertext,idle_expires_at,absolute_expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, digest(id), tenant, subject, displayName, ciphertext, digest(csrf), csrfCiphertext, now.Add(30*time.Minute), absolute)
	if err != nil {
		return "", Session{}, err
	}
	return id, Session{Principal: model.Principal{Tenant: tenant, Subject: subject, SessionVersion: 1, SessionHash: digestHex(id)}, DisplayName: displayName, CSRF: csrf, AbsoluteExpires: absolute}, nil
}

func (s *Store) Get(ctx context.Context, id, csrf string, requireCSRF bool) (Session, error) {
	now := s.Now().UTC()
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return Session{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var session Session
	var csrfHash, csrfCiphertext []byte
	err = tx.QueryRow(ctx, `SELECT tenant_id,subject_id,display_name,csrf_hash,csrf_ciphertext,version,absolute_expires_at FROM sessions WHERE id_hash=$1 AND idle_expires_at>$2 AND absolute_expires_at>$2 FOR UPDATE`, digest(id), now).Scan(&session.Principal.Tenant, &session.Principal.Subject, &session.DisplayName, &csrfHash, &csrfCiphertext, &session.Principal.SessionVersion, &session.AbsoluteExpires)
	if errors.Is(err, pgx.ErrNoRows) {
		return Session{}, ErrInvalid
	}
	if err != nil {
		return Session{}, err
	}
	session.Principal.SessionHash = digestHex(id)
	if requireCSRF && (csrf == "" || subtle.ConstantTimeCompare(csrfHash, digest(csrf)) != 1) {
		return Session{}, ErrInvalid
	}
	plainCSRF, err := s.open(csrfCiphertext)
	if err != nil {
		return Session{}, ErrInvalid
	}
	session.CSRF = string(plainCSRF)
	idle := now.Add(30 * time.Minute)
	if idle.After(session.AbsoluteExpires) {
		idle = session.AbsoluteExpires
	}
	if _, err = tx.Exec(ctx, `UPDATE sessions SET idle_expires_at=$2 WHERE id_hash=$1`, digest(id), idle); err != nil {
		return Session{}, err
	}
	if err = tx.Commit(ctx); err != nil {
		return Session{}, err
	}
	return session, nil
}

func (s *Store) Revoke(ctx context.Context, id string) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	_, err := s.Pool.Exec(ctx, `DELETE FROM sessions WHERE id_hash=$1`, digest(id))
	return err
}
func (s *Store) seal(plaintext []byte) ([]byte, error) {
	nonce := make([]byte, s.AEAD.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}
	return s.AEAD.Seal(nonce, nonce, plaintext, nil), nil
}
func (s *Store) open(ciphertext []byte) ([]byte, error) {
	if len(ciphertext) < s.AEAD.NonceSize() {
		return nil, ErrInvalid
	}
	nonce := ciphertext[:s.AEAD.NonceSize()]
	return s.AEAD.Open(nil, nonce, ciphertext[s.AEAD.NonceSize():], nil)
}
func digest(value string) []byte { sum := sha256.Sum256([]byte(value)); return sum[:] }
func digestHex(value string) string {
	sum := sha256.Sum256([]byte(value))
	return fmt.Sprintf("%x", sum[:])
}
func random(size int) string {
	value := make([]byte, size)
	if _, err := rand.Read(value); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(value)
}
