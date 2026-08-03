# Document Upload Example Implementation-Handoff Acceptance Criteria

Implementation may begin only when every blocking decision in `decision-register.yaml` has a named human owner, disposition, date, and evidence reference, and the independent infrastructure/security gates are non-blocking.

## Architecture and identity

- Approved architecture/data-flow diagrams identify public, private, administrative, CI/CD, scanner, and data trust boundaries.
- OIDC issuer/audience/claims, BFF ownership, redirects, session/cookie/CSRF behavior, expiry, logout, and revocation are approved.
- Tenant source of truth, authorization matrix, sharing/admin behavior, and audit semantics are approved.

## Data and content lifecycle

- Classification, permitted formats/sizes, quotas, retention, legal hold, deletion, download/rendering, and backup-expiry rules are approved.
- Object-store and scanner products, encryption/key ownership, quarantine/promotion, sandbox, update/re-scan, and fail-closed rules are approved.
- Document and job state machines have no path that retrieves non-clean content.
- Reconciliation, orphan cleanup, idempotency, concurrency, and stale-worker behavior have testable invariants.

## PostgreSQL and recovery

- Version/topology/operator, capacity, roles, migration tool, HA, maintenance, RPO/RTO, backup/PITR, restore order, and test cadence are approved.
- Schema and API contracts are reviewed; expand/migrate/contract and mixed-version compatibility are demonstrated in a disposable database.
- Pool, timeout, transaction, retry, slow-query, lock, and index behavior has objective thresholds.

## Platform and delivery

- Proxmox/Talos capacity and failure-domain mapping, CNI/network policy, ingress/TLS/DNS, RBAC, pod security, quotas, storage classes, secret mechanism, observability, and policy enforcement are selected.
- Terraform provider/backend/credential/recovery design and GitLab runner/registry/signing/provenance/admission design are approved.
- Helm render, schema, RBAC, network policy, secret-reference, hook/CRD, cluster-scope, image pinning, and uninstall/rollback checks are reproducible.
- No persistent mutation occurs without the autonomy-policy human gate.

## Frontend and testing

- Node/package manager/framework or build tool, styling/component system, supported browsers, accessibility target, and unit/component/browser test stack are approved project choices.
- UI covers idle, validation, upload, progress, cancellation, processing, clean, rejection, safe error, expired authorization, retry, and deletion states.
- Gherkin scenarios cover critical/high risks, including authorization, CSRF/session, malicious content, scanning, idempotency, partial failure, migration, restore, rollback, accessibility, isolation, and overload.

## Evidence and gates

- Exact revision, immutable artifacts, SBOM/provenance/signatures, test/scan results, rendered manifests, Terraform plan, migration analysis, rollback, and recovery evidence are available.
- Threat modeler, infrastructure reviewer, pipeline-security reviewer, security reviewer, and applicable compliance owner return non-blocking dispositions.
- Code review is performed by an agent/human independent of implementation.
