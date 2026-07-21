# Document Upload Example Design Resolution

This package resolves planning blockers far enough for independent architecture, threat, infrastructure, pipeline-security, and security review.

All decisions are **proposed** until the named human owner approves them. No artifact authorizes implementation, deployment, migration, Terraform state access, or production changes.

## Contents

| Artifact | Purpose |
|---|---|
| `architecture.md` | Component, trust-boundary, deployment, and recovery baseline |
| `data-flow.md` | Authentication, upload, scan, retrieval, and deletion flows |
| `state-machines.md` | Document, scan-job, and deployment invariants |
| `api-contract.md` | Proposed browser/BFF/API operations and error semantics |
| `data-model.md` | Proposed PostgreSQL entities, constraints, and roles |
| `decision-register.yaml` | Machine-readable decisions, owners, and blocking status |
| `local-slice-decisions.yaml` | Requester-approved choices scoped only to the local demonstration |
| `acceptance-criteria.md` | Testable requirements for implementation handoff |
| `risk-register.md` | Threat disposition and residual-risk ownership |
| `review-package.md` | Evidence checklist and gate re-dispatch instructions |
| `adrs/` | Individual proposed architecture decisions |

## Proposed baseline

- Same-origin React frontend and backend-for-frontend (BFF) using OIDC Authorization Code with PKCE.
- Secure, HttpOnly session cookie; OIDC tokens remain server-side.
- Go internal API using pgx v5 and PostgreSQL for metadata, sessions, idempotency, audit/outbox, and scan jobs.
- Separate object storage with quarantine and clean namespaces; implementation product remains a human decision.
- Scanner isolated from application/database credentials; only a trusted promotion component can make clean content retrievable.
- Kubernetes namespace isolation, dedicated service accounts, default-deny network policies, restricted pods, pinned images/charts, and secrets outside Helm values.
- GitLab builds once and promotes the same signed immutable artifact through protected environments.

## Remaining human decisions

Items marked `human-decision-required` in `decision-register.yaml` remain blocking. The most important are data classification/retention, object-store and scanner products, PostgreSQL topology and RPO/RTO, Proxmox/Talos capacity/failure-domain mapping, Terraform provider/backend, Kubernetes CNI/policy engine, secrets/signing platforms, GitLab runner trust tiers, and frontend tooling/accessibility targets.

The local decision overlay does not close, replace, or approve any production decision.
