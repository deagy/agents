# ADR 0003: Quarantine, Scan, and Trusted Promotion

- Status: Proposed — product selections required
- Owners: Platform, security, and data owner

## Context

Uploaded documents are untrusted. A scanner verdict cannot safely expose an object unless it is bound to the exact bytes and transition.

## Decision

Store uploads in a private quarantine namespace. An isolated scanner reads quarantine and records a verdict bound to tenant, document ID, object version, size, hash, engine/version, and policy version. The scanner cannot access clean storage or application/database credentials beyond its narrow job/verdict needs.

A separate trusted promotion worker verifies the expected state/version/hash, copies clean content to an immutable clean namespace, and commits the clean locator/state. Only `clean` content is retrievable.

## Consequences

- PostgreSQL and object storage are not atomic; reconciliation is mandatory.
- Scanner/product updates require re-scan policy and signature freshness monitoring.
- Storage cost includes quarantine, clean objects, and versioning/retention.

## Approval criteria

Select object-store and scanner products; approve permitted formats/sizes, archive limits, scanner sandbox, update/re-scan policy, retention/deletion, encryption/key ownership, and fail-closed behavior.
