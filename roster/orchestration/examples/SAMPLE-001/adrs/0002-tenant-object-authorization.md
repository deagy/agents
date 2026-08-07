# ADR 0002: Server-Side Tenant and Object Authorization

- Status: Proposed — human approval required
- Owners: Product/data owner and security

## Context

Document IDs and tenant/owner fields from a browser cannot be trusted. Every document operation can become an IDOR or cross-tenant access path.

## Decision

Map validated OIDC claims to an internal subject and tenant at the BFF/API boundary. The API derives ownership server-side and authorizes create, status, content, share, and delete independently. PostgreSQL queries include tenant/authorization scope; object keys are opaque and never grant access by themselves.

Use explicit grants only if sharing is required. Audit every allow/deny decision for sensitive operations using opaque identifiers.

## Consequences

- Identity-provider claim changes require controlled mapping/versioning.
- Support and administration need separate, audited roles rather than tenant bypasses.
- Tests must cover enumeration and every cross-user/cross-tenant operation.

## Approval criteria

Approve tenant source of truth, subject/tenant claim mapping, sharing model, administrative access, disabled-user behavior, audit retention, and authorization matrix.
