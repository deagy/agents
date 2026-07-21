# Production Release Workflow

## Preconditions

- All applicable gates in `../orchestration/quality-gates.md` are satisfied.
- Artifact digests, source revision, provenance, SBOM, plans, approvals, change window, owners, verification thresholds, and rollback are recorded.
- Critical/high findings are resolved or covered by authorized, time-bound exceptions.

## Execution

1. Release engineer validates preconditions and prevents conflicting releases.
2. Authorized human approves the exact artifact, environment, plan, and window.
3. Scoped deployment identity promotes and deploys the immutable artifact, progressively where appropriate.
4. Test engineer or automated verification checks health, security, business, data-integrity, and observability thresholds.
5. Release engineer records the result; technical writer and evidence curator update release documentation and evidence.

## Stop conditions

Stop and roll back or invoke incident response on identity mismatch, artifact mismatch, failed migration, unavailable telemetry, breached error/latency/security thresholds, unexpected infrastructure actions, or unverifiable state.
