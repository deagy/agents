package repository

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/sample-001/services/internal/model"
)

var (
	ErrNotFound            = errors.New("document not found")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with different request")
	ErrReplay              = errors.New("assertion already consumed")
	ErrStaleLease          = errors.New("job lease is stale")
	ErrQuota               = errors.New("owner document quota exceeded")
)

const maxOwnerDocuments = 20
const maxOwnerBytes int64 = 250 * 1024 * 1024

type Store interface {
	ReserveUpload(ctx context.Context, principal model.Principal, idempotencyKey, requestHash, name, policy string) (model.Document, bool, error)
	CommitUpload(ctx context.Context, principal model.Principal, id string, staged model.CreateInput, requestID string) (model.Document, error)
	FailUpload(ctx context.Context, principal model.Principal, id, code, requestID string) error
	Get(ctx context.Context, principal model.Principal, id string) (model.Document, error)
	MarkDeleting(ctx context.Context, principal model.Principal, id, requestID string) error
}

type Memory struct {
	mu         sync.Mutex
	documents  map[string]model.Document
	keys       map[string]memoryKey
	assertions map[string]time.Time
}

type memoryKey struct {
	RequestHash string
	DocumentID  string
}

func NewMemory() *Memory {
	return &Memory{documents: map[string]model.Document{}, keys: map[string]memoryKey{}, assertions: map[string]time.Time{}}
}

func ownerKey(principal model.Principal, value string) string {
	return principal.Tenant + "\x00" + principal.Subject + "\x00" + value
}

func (m *Memory) ReserveUpload(_ context.Context, p model.Principal, key, requestHash, name, policy string) (model.Document, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	mapKey := ownerKey(p, key)
	if existing, ok := m.keys[mapKey]; ok {
		if existing.RequestHash != requestHash {
			return model.Document{}, false, ErrIdempotencyConflict
		}
		return m.documents[existing.DocumentID], true, nil
	}
	owned := 0
	for _, document := range m.documents {
		if document.Tenant == p.Tenant && document.Subject == p.Subject && document.Status != "deleted" {
			owned++
		}
	}
	if owned >= maxOwnerDocuments {
		return model.Document{}, false, ErrQuota
	}
	now := time.Now().UTC()
	document := model.Document{ID: uuid.NewString(), Tenant: p.Tenant, Subject: p.Subject, Name: name, Status: "uploading", PolicyVersion: policy, ObjectVersion: 1, CreatedAt: now, UpdatedAt: now}
	m.documents[document.ID] = document
	m.keys[mapKey] = memoryKey{RequestHash: requestHash, DocumentID: document.ID}
	return document, false, nil
}

func (m *Memory) CommitUpload(_ context.Context, p model.Principal, id string, input model.CreateInput, _ string) (model.Document, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	document, ok := m.documents[id]
	if !ok || document.Tenant != p.Tenant || document.Subject != p.Subject || document.Status != "uploading" {
		return model.Document{}, ErrNotFound
	}
	document.MediaType, document.Size, document.SHA256, document.ObjectKey = input.MediaType, input.Size, input.SHA256, input.ObjectKey
	document.Status, document.UpdatedAt = "pending_scan", time.Now().UTC()
	m.documents[id] = document
	return document, nil
}

func (m *Memory) FailUpload(_ context.Context, p model.Principal, id, code, _ string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	document, ok := m.documents[id]
	if !ok || document.Tenant != p.Tenant || document.Subject != p.Subject {
		return ErrNotFound
	}
	document.Status, document.Message, document.UpdatedAt = "failed", code, time.Now().UTC()
	m.documents[id] = document
	return nil
}

func (m *Memory) Get(_ context.Context, p model.Principal, id string) (model.Document, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	document, ok := m.documents[id]
	if !ok || document.Tenant != p.Tenant || document.Subject != p.Subject || document.Status == "deleted" {
		return model.Document{}, ErrNotFound
	}
	return document, nil
}

func (m *Memory) MarkDeleting(_ context.Context, p model.Principal, id, _ string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	document, ok := m.documents[id]
	if !ok || document.Tenant != p.Tenant || document.Subject != p.Subject {
		return ErrNotFound
	}
	document.Status, document.UpdatedAt = "deleting", time.Now().UTC()
	m.documents[id] = document
	return nil
}

func (m *Memory) Consume(_ context.Context, jti, sessionHash, tenant, subject string, sessionVersion int64, expiresAt time.Time) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if sessionHash == "" || tenant == "" || subject == "" || sessionVersion < 1 {
		return ErrReplay
	}
	now := time.Now()
	for key, expiry := range m.assertions {
		if expiry.Before(now) {
			delete(m.assertions, key)
		}
	}
	if _, exists := m.assertions[jti]; exists {
		return ErrReplay
	}
	m.assertions[jti] = expiresAt
	return nil
}

func (m *Memory) SetStatus(id, status string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	document := m.documents[id]
	document.Status = status
	document.UpdatedAt = time.Now().UTC()
	m.documents[id] = document
}

type Postgres struct{ Pool *pgxpool.Pool }

func NewPostgres(ctx context.Context, databaseURL string) (*Postgres, error) {
	config, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse database config: %w", err)
	}
	config.MaxConns = 10
	config.MinConns = 1
	config.MaxConnLifetime = 30 * time.Minute
	config.MaxConnIdleTime = 5 * time.Minute
	connectCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(connectCtx, config)
	if err != nil {
		return nil, fmt.Errorf("connect database: %w", err)
	}
	if err := pool.Ping(connectCtx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping database: %w", err)
	}
	return &Postgres{Pool: pool}, nil
}

func keyDigest(value string) []byte { sum := sha256.Sum256([]byte(value)); return sum[:] }

func (p *Postgres) ReserveUpload(ctx context.Context, principal model.Principal, key, requestHash, name, policy string) (model.Document, bool, error) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	tx, err := p.Pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
	if err != nil {
		return model.Document{}, false, err
	}
	defer tx.Rollback(ctx)
	var existingHash string
	var existingID string
	err = tx.QueryRow(ctx, `SELECT encode(request_hash,'hex'), document_id::text FROM idempotency_keys WHERE tenant_id=$1 AND subject_id=$2 AND key_hash=$3`, principal.Tenant, principal.Subject, keyDigest(key)).Scan(&existingHash, &existingID)
	if err == nil {
		if existingHash != requestHash {
			return model.Document{}, false, ErrIdempotencyConflict
		}
		doc, err := getWith(ctx, tx, principal, existingID)
		return doc, true, err
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return model.Document{}, false, err
	}
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1 || chr(0) || $2,0))`, principal.Tenant, principal.Subject); err != nil {
		return model.Document{}, false, err
	}
	var owned int
	if err = tx.QueryRow(ctx, `SELECT count(*) FROM documents WHERE tenant_id=$1 AND subject_id=$2 AND status <> 'deleted'`, principal.Tenant, principal.Subject).Scan(&owned); err != nil {
		return model.Document{}, false, err
	}
	if owned >= maxOwnerDocuments {
		return model.Document{}, false, ErrQuota
	}
	id := uuid.NewString()
	if _, err = tx.Exec(ctx, `INSERT INTO documents(id,tenant_id,subject_id,original_name,policy_version,status) VALUES($1,$2,$3,$4,$5,'uploading')`, id, principal.Tenant, principal.Subject, name, policy); err != nil {
		return model.Document{}, false, err
	}
	decoded, err := hex.DecodeString(requestHash)
	if err != nil {
		return model.Document{}, false, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO idempotency_keys(tenant_id,subject_id,key_hash,request_hash,document_id) VALUES($1,$2,$3,$4,$5)`, principal.Tenant, principal.Subject, keyDigest(key), decoded, id); err != nil {
		return model.Document{}, false, err
	}
	if err = tx.Commit(ctx); err != nil {
		return model.Document{}, false, err
	}
	document, err := p.Get(ctx, principal, id)
	return document, false, err
}

func (p *Postgres) CommitUpload(ctx context.Context, principal model.Principal, id string, input model.CreateInput, requestID string) (model.Document, error) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return model.Document{}, err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1 || chr(0) || $2,0))`, principal.Tenant, principal.Subject); err != nil {
		return model.Document{}, err
	}
	var currentBytes int64
	if err = tx.QueryRow(ctx, `SELECT COALESCE(sum(byte_size),0) FROM documents WHERE tenant_id=$1 AND subject_id=$2 AND status <> 'deleted' AND id<>$3`, principal.Tenant, principal.Subject, id).Scan(&currentBytes); err != nil {
		return model.Document{}, err
	}
	if currentBytes+input.Size > maxOwnerBytes {
		return model.Document{}, ErrQuota
	}
	command, err := tx.Exec(ctx, `UPDATE documents SET media_type=$4,byte_size=$5,sha256=$6,object_key=$7,status='pending_scan',updated_at=now() WHERE id=$1 AND tenant_id=$2 AND subject_id=$3 AND status='uploading'`, id, principal.Tenant, principal.Subject, input.MediaType, input.Size, input.SHA256, input.ObjectKey)
	if err != nil || command.RowsAffected() != 1 {
		if err == nil {
			err = ErrNotFound
		}
		return model.Document{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO jobs(kind,document_id) VALUES('scan',$1)`, id); err != nil {
		return model.Document{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO audit_events(request_id,tenant_id,subject_id,document_id,event_type,outcome) VALUES($1,$2,$3,$4,'document.uploaded','success')`, requestID, principal.Tenant, principal.Subject, id); err != nil {
		return model.Document{}, err
	}
	if err = tx.Commit(ctx); err != nil {
		return model.Document{}, err
	}
	return p.Get(ctx, principal, id)
}

func (p *Postgres) FailUpload(ctx context.Context, principal model.Principal, id, code, requestID string) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	_, err := p.Pool.Exec(ctx, `UPDATE documents SET status='failed',status_message=$4,updated_at=now() WHERE id=$1 AND tenant_id=$2 AND subject_id=$3 AND status='uploading'`, id, principal.Tenant, principal.Subject, code)
	return err
}

func (p *Postgres) Get(ctx context.Context, principal model.Principal, id string) (model.Document, error) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	return getWith(ctx, p.Pool, principal, id)
}

type rowQuerier interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}

func getWith(ctx context.Context, query rowQuerier, principal model.Principal, id string) (model.Document, error) {
	var doc model.Document
	err := query.QueryRow(ctx, `SELECT id::text,tenant_id,subject_id,original_name,COALESCE(media_type,''),COALESCE(byte_size,0),COALESCE(sha256,''),COALESCE(object_key::text,''),status::text,COALESCE(status_message,''),policy_version,object_version,created_at,updated_at FROM documents WHERE id=$1 AND tenant_id=$2 AND subject_id=$3 AND status <> 'deleted'`, id, principal.Tenant, principal.Subject).Scan(&doc.ID, &doc.Tenant, &doc.Subject, &doc.Name, &doc.MediaType, &doc.Size, &doc.SHA256, &doc.ObjectKey, &doc.Status, &doc.Message, &doc.PolicyVersion, &doc.ObjectVersion, &doc.CreatedAt, &doc.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.Document{}, ErrNotFound
	}
	return doc, err
}

func (p *Postgres) MarkDeleting(ctx context.Context, principal model.Principal, id, requestID string) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	command, err := tx.Exec(ctx, `UPDATE documents SET status='deleting',updated_at=now() WHERE id=$1 AND tenant_id=$2 AND subject_id=$3 AND status <> 'deleted'`, id, principal.Tenant, principal.Subject)
	if err != nil || command.RowsAffected() != 1 {
		if err == nil {
			err = ErrNotFound
		}
		return err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO jobs(kind,document_id) VALUES('deletion',$1)`, id); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO audit_events(request_id,tenant_id,subject_id,document_id,event_type,outcome) VALUES($1,$2,$3,$4,'document.delete_requested','success')`, requestID, principal.Tenant, principal.Subject, id); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (p *Postgres) Consume(ctx context.Context, jti, sessionHash, tenant, subject string, sessionVersion int64, expiresAt time.Time) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var active bool
	err = tx.QueryRow(ctx, `SELECT EXISTS (
		SELECT 1 FROM active_sessions
		WHERE id_hash=decode($1,'hex') AND tenant_id=$2 AND subject_id=$3 AND version=$4
	)`, sessionHash, tenant, subject, sessionVersion).Scan(&active)
	if err != nil || !active {
		return ErrReplay
	}
	command, err := tx.Exec(ctx, `INSERT INTO consumed_assertions(jti,expires_at,tenant_id,subject_id) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`, jti, expiresAt, tenant, subject)
	if err != nil {
		return err
	}
	if command.RowsAffected() != 1 {
		return ErrReplay
	}
	return tx.Commit(ctx)
}
