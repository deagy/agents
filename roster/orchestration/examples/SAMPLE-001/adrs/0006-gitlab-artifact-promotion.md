# ADR 0006: GitLab Build-Once Artifact Promotion

- Status: Proposed — runner/signing products required
- Owners: CI/CD, platform, and security

## Context

Untrusted merge-request code must not access deployment identities, protected variables, privileged runners, or production environments.

## Decision

Use separate GitLab runner trust tiers. Untrusted pipelines receive no protected secrets or deployment credentials. Pin includes, images, tools, providers, modules, charts, and actions to reviewed immutable versions.

Run TypeScript/React, Go, Gherkin, dependency, secret, SAST, Terraform, Helm, container, SBOM, provenance, and signature checks as applicable. Build once, sign, and promote the same digest through protected environments. Deployment jobs use short-lived scoped identities and explicit human production approval.

## Consequences

- Runner isolation, registry, signing, provenance, and admission verification become platform dependencies.
- Generated Mockery outputs and rendered manifests require reproducibility checks.

## Approval criteria

Approve runner placement/trust tiers, protected branches/environments/variables, registry, signing/provenance, admission policy, artifact retention, deployment identities, and emergency procedure.
