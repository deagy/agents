# SAMPLE-001 PostgreSQL Data Model

## Proposed entities

### `sessions`

- Opaque session ID hash, subject, tenant, encrypted/protected token material reference, created/last-seen/idle-expiry/absolute-expiry, version, and revoked timestamp.
- Never store the browser cookie value in plaintext.

### `documents`

- UUID, tenant ID, owner subject, original filename (classified), safe display filename, declared/detected media type, byte size, SHA-256, quarantine locator, clean locator, status, scan-policy version, retention/deletion fields, timestamps, and optimistic version.
- Index every authorization query by tenant plus document ID/owner as applicable.

### `document_grants`

- Optional document, tenant, principal, permission, issuer, creation and revocation metadata.
- Omit the table entirely if product owners reject sharing.

### `idempotency_records`

- Tenant, subject, operation, key hash, request digest, response binding, state, and expiry.
- Unique constraint on tenant/subject/operation/key hash.

### `scan_jobs`

- Document/version/policy identity, state, lease owner/expiry, attempt count, next attempt, last safe error code, and timestamps.
- Unique logical job per document version and scan-policy version.

### `scan_results`

- Document/version/hash, engine and signature version, verdict, evidence reference, scanner workload identity, and timestamp.
- Append-only; corrections create a new result/policy version.

### `promotion_jobs`

- Document/version/hash, expected state, lease fields, destination version, attempt data, and timestamps.

### `audit_events`

- Event ID, tenant, actor, action, resource ID, allow/deny/result, request ID, source identity, timestamp, and structured non-sensitive metadata.
- Append-only with retention and tamper-resistance controls defined by the evidence policy.

## Transaction boundaries

- Upload bytes are not held inside a PostgreSQL transaction.
- After quarantine commit, one transaction creates/updates document metadata, binds idempotency, creates the scan job, and appends audit/outbox evidence.
- Promotion uses expected document version/hash; clean locator/state and audit event commit together after object copy succeeds.
- Deletion records intent before object operations and marks completion only after required deletions are verified.

## Database roles

- BFF session role: sessions only.
- API role: document metadata, grants, idempotency, audit insertion, and job creation; no schema administration.
- Scanner role: claim scan jobs and append verdicts; no session, grant, clean-storage, or schema access.
- Promotion role: claim promotion jobs and update expected lifecycle fields only.
- Migration role: separately injected, human-gated, unavailable to runtime workloads.
- Read-only operational role: approved metadata/health views with sensitive columns excluded.
