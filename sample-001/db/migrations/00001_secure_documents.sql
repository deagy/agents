-- +goose Up
CREATE TYPE document_status AS ENUM ('uploading', 'pending_scan', 'scanning', 'clean', 'rejected', 'failed', 'deleting', 'deleted');
CREATE TYPE job_status AS ENUM ('ready', 'leased', 'complete', 'dead');

CREATE TABLE sessions (
    id_hash bytea PRIMARY KEY,
    tenant_id text NOT NULL,
    subject_id text NOT NULL,
    display_name text NOT NULL,
    token_ciphertext bytea NOT NULL,
    csrf_hash bytea NOT NULL,
    csrf_ciphertext bytea NOT NULL,
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    idle_expires_at timestamptz NOT NULL,
    absolute_expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (idle_expires_at <= absolute_expires_at)
);

CREATE TABLE documents (
    id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    subject_id text NOT NULL,
    original_name text NOT NULL,
    media_type text,
    byte_size bigint CHECK (byte_size >= 0 AND byte_size <= 26214400),
    sha256 char(64),
    object_key uuid,
    object_version bigint NOT NULL DEFAULT 1 CHECK (object_version > 0),
    policy_version text NOT NULL,
    status document_status NOT NULL,
    status_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, subject_id, id),
    CHECK ((status = 'uploading') OR (sha256 IS NOT NULL AND object_key IS NOT NULL AND byte_size IS NOT NULL))
);
CREATE INDEX documents_owner_created_idx ON documents (tenant_id, subject_id, created_at DESC);

CREATE TABLE idempotency_keys (
    tenant_id text NOT NULL,
    subject_id text NOT NULL,
    key_hash bytea NOT NULL,
    request_hash bytea NOT NULL,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_id, key_hash)
);

CREATE TABLE scan_results (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    object_version bigint NOT NULL,
    policy_version text NOT NULL,
    sha256 char(64) NOT NULL,
    byte_size bigint NOT NULL,
    verdict text NOT NULL CHECK (verdict IN ('clean', 'rejected', 'error')),
    scanner_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('scan', 'promotion', 'deletion', 'reconciliation')),
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status job_status NOT NULL DEFAULT 'ready',
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at timestamptz NOT NULL DEFAULT now(),
    leased_until timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0,
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_claim_idx ON jobs (kind, status, available_at, leased_until, id);

CREATE TABLE audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    request_id text NOT NULL,
    tenant_id text NOT NULL,
    subject_id text NOT NULL,
    document_id uuid,
    event_type text NOT NULL,
    outcome text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_owner_time_idx ON audit_events (tenant_id, subject_id, occurred_at DESC);

CREATE TABLE consumed_assertions (
    jti uuid PRIMARY KEY,
    expires_at timestamptz NOT NULL,
    tenant_id text NOT NULL,
    subject_id text NOT NULL
);
CREATE INDEX consumed_assertions_expiry_idx ON consumed_assertions (expires_at);

CREATE VIEW active_sessions AS
SELECT id_hash, tenant_id, subject_id, display_name, csrf_hash, version, idle_expires_at, absolute_expires_at
FROM sessions
WHERE idle_expires_at > now() AND absolute_expires_at > now();

-- Capability roles are intentionally NOLOGIN. Disposable Compose creates one
-- login per process and grants exactly one of these roles.
CREATE ROLE sample001_bff NOLOGIN;
CREATE ROLE sample001_api NOLOGIN;
CREATE ROLE sample001_scanner NOLOGIN;
CREATE ROLE sample001_promotion NOLOGIN;
CREATE ROLE sample001_deletion NOLOGIN;

GRANT USAGE ON SCHEMA public TO sample001_bff, sample001_api, sample001_scanner, sample001_promotion, sample001_deletion;
GRANT SELECT, INSERT, UPDATE, DELETE ON sessions TO sample001_bff;
GRANT SELECT ON active_sessions TO sample001_api;
GRANT SELECT, INSERT, UPDATE ON documents, idempotency_keys, jobs, audit_events, consumed_assertions TO sample001_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sample001_api;
GRANT SELECT, UPDATE ON documents, jobs TO sample001_scanner;
GRANT INSERT ON scan_results, jobs TO sample001_scanner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sample001_scanner;
GRANT SELECT, UPDATE ON documents, jobs TO sample001_promotion;
GRANT SELECT, UPDATE ON documents, jobs TO sample001_deletion;

-- +goose Down
REASSIGN OWNED BY sample001_bff, sample001_api, sample001_scanner, sample001_promotion, sample001_deletion TO CURRENT_USER;
DROP OWNED BY sample001_bff, sample001_api, sample001_scanner, sample001_promotion, sample001_deletion;
DROP ROLE IF EXISTS sample001_bff, sample001_api, sample001_scanner, sample001_promotion, sample001_deletion;
DROP VIEW IF EXISTS active_sessions;
DROP TABLE IF EXISTS consumed_assertions;
DROP TABLE IF EXISTS audit_events;
DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS scan_results;
DROP TABLE IF EXISTS idempotency_keys;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS sessions;
DROP TYPE IF EXISTS job_status;
DROP TYPE IF EXISTS document_status;
