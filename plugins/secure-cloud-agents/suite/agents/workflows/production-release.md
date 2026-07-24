<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Production Release Workflow

## Preconditions (G8 Release Readiness)

- G1-G7 and all applicable specialist attestations in `../orchestration/quality-gates.md` are approved for the exact release inputs.
- Artifact digests, source revision, provenance, SBOM, plans, approvals, change window, owners, verification thresholds, and rollback are recorded.
- Critical/high findings are resolved or covered by authorized, time-bound exceptions.

## Execution

1. Release engineer validates preconditions and prevents conflicting releases.
2. Authorized Human Release Authority decides G9 for the exact artifact, environment, deployment identity, plan, window, blast radius, rollback, and verification thresholds. Any mismatch, substitution, or stale approval returns to G8.
3. Scoped deployment identity promotes and deploys the immutable artifact, progressively where appropriate.
4. Test engineer or automated verification checks health, security, business, data-integrity, and observability thresholds.
5. Release engineer records the result; technical writer and evidence curator update release documentation and evidence without approving or manufacturing it.
6. Continue with `runtime-assurance.md`; the Human Service Owner decides G10 after the defined observation window.

## Stop conditions

Stop and roll back or invoke incident response on identity mismatch, artifact mismatch, failed migration, unavailable telemetry, breached error/latency/security thresholds, unexpected infrastructure actions, or unverifiable state.
