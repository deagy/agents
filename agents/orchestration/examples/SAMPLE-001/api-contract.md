# SAMPLE-001 API Contract

## Boundary

The browser calls same-origin `/api/*` endpoints on the BFF. The BFF authenticates the session, enforces CSRF for state changes, and forwards a short-lived internal identity assertion over authenticated private transport. The document API never trusts browser-supplied subject, tenant, or role values.

## Operations

| Operation | Request | Success | Authorization |
|---|---|---|---|
| `POST /api/v1/documents` | Multipart stream, CSRF token, `Idempotency-Key` | `202` with document ID and `pending_scan` | `document:create` plus tenant quota |
| `GET /api/v1/documents/{id}` | Document ID | `200` metadata/status | Object-level `document:read` |
| `GET /api/v1/documents/{id}/content` | Document ID | `200` streamed clean content | Object-level `document:read`; state must be `clean` |
| `DELETE /api/v1/documents/{id}` | CSRF token | `202` with `delete_pending` | Object-level `document:delete` and retention policy |

The approved maximum size, permitted formats, and quotas are configuration validated at startup and enforced server-side while streaming. Client checks are advisory only.

## Create response

```json
{
  "document_id": "opaque-uuid",
  "status": "pending_scan",
  "created_at": "2026-07-21T00:00:00Z",
  "request_id": "opaque-request-id"
}
```

## Error contract

Return a stable code, safe message, and request ID. Never return raw SQL/storage/scanner errors, tokens, internal paths, stack traces, or document content.

| HTTP | Stable codes |
|---:|---|
| 400 | `invalid_request`, `unsupported_type`, `size_limit_exceeded` |
| 401 | `authentication_required`, `session_expired` |
| 403 | `not_authorized`, `retention_hold` |
| 404 | `document_not_found` without cross-tenant disclosure |
| 409 | `idempotency_conflict`, `invalid_state` |
| 413 | `size_limit_exceeded` |
| 429 | `rate_limited`, `quota_exceeded` |
| 503 | `storage_unavailable`, `processing_unavailable` |

## Required headers and behavior

- Correlation/request ID on every response.
- `Cache-Control: no-store` for session and sensitive metadata responses.
- Safe `Content-Disposition` and `X-Content-Type-Options: nosniff` on downloads.
- CSP and related browser headers defined at the BFF/ingress.
- Constant authorization semantics: callers cannot distinguish another tenant's object from a nonexistent object.
- Bounded request/header/body timeouts and cancellation propagation.
- Idempotency key reuse with a different tenant/subject/digest returns `409`.
