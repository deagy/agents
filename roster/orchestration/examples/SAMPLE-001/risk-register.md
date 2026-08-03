# Document Upload Example Risk Register

All risks remain open until required decisions and verification evidence are approved. Risk acceptance is human-only.

| ID | Severity | Risk | Proposed controls | Required verification | Owner role |
|---|---|---|---|---|---|
| R-001 | High | Cross-tenant or object-level authorization bypass | Server-derived tenant/subject, scoped queries, explicit grants, uniform not-found behavior | Cross-user/tenant create/read/status/delete tests | Product and security |
| R-002 | High | Malicious or unscanned content becomes retrievable | Quarantine, isolated scanner, exact hash/version verdict, trusted promotion, clean-only reads | Malformed/polyglot/archive/scanner-failure Gherkin scenarios | Security and platform |
| R-003 | High | Token theft, CSRF, fixation, or redirect abuse | Same-origin BFF, server-side tokens, secure cookie, PKCE/state/nonce, CSRF, redirect allowlist | Browser/session negative tests and data-flow review | Application and security |
| R-004 | High | Metadata/object divergence or duplicate processing | Idempotency binding, state/version fences, leased jobs, reconciliation | Partial failure, stale worker, duplicate event, orphan repair tests | Backend and data |
| R-005 | High | Scanner compromise or lateral movement | Dedicated identity, no clean-store/app secrets, restricted pod, denied egress, resource bounds | Rendered policy review and sandbox escape/lateral-flow tests | Platform and security |
| R-006 | High | Resource exhaustion and denial of service | Stream limits, quotas, rate/concurrency limits, archive bounds, bounded retries, capacity alerts | Load/backpressure/pool/queue/storage exhaustion tests | Service owner |
| R-007 | High | Supply-chain or deployment identity compromise | Isolated runners, pinning, SBOM, provenance/signing, admission, protected environments | Pipeline threat review and signature/admission failure tests | CI/CD and security |
| R-008 | High | Unrecoverable PostgreSQL/blob loss or inconsistent restore | Encrypted backups, PITR/versioning, ordered restore, reconciliation, tested RPO/RTO | Full restore and consistency test in isolated environment | Database/platform owner |
| R-009 | Medium | XSS or unsafe active-document rendering | Output encoding, CSP, isolated/download-only content handling, dependency controls | Malicious filename/content and CSP regression tests | Frontend and security |
| R-010 | Medium | Audit gaps or sensitive logging | Correlated append-only audit, redaction, least access, retention | Log-content assertions and audit completeness/integrity tests | Security/evidence owner |

## Residual risk

Even after controls, novel malicious content, delayed identity revocation, storage/database non-atomicity, and platform/registry compromise remain material. Owners must define accepted residual risk only after verification evidence exists.
