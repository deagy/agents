---
name: release-evidence-package
description: Assemble auditable release or demo-package evidence for this repository. Use when collecting source revisions, test results, scans, SBOMs, checksums, rendered manifests, Terraform validation, reviews, approvals, exceptions, and unavailable-tool reports.
---

> Packaged suite note: when the current project has no local `agents/` tree, resolve suite files under `../../suite/agents/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.


# Release Evidence Package

Use this skill to create or review an evidence bundle. Evidence supports a decision; it does not approve release, accept risk, deploy, or override missing gates.

## Evidence checklist

Collect and index:

- Exact source revision, changed paths, task ID, and scope exclusions.
- Build artifacts, checksums, SBOMs, provenance/signing status, and artifact retention location.
- Unit, integration, Gherkin, frontend, race, accessibility, security, dependency, container, secret-scan, Helm render/lint, Terraform validate, and policy-check results as applicable.
- Architecture, code, infrastructure, pipeline, security, compliance, support, and release reviews with dispositions.
- Human approvals or explicit missing-owner blockers for production, destructive, privileged, risk-acceptance, or persistent-environment actions.
- Unavailable validations with reason, host/tool constraints, and proposed prepared-runner follow-up.

## Guardrails

- Do not copy secrets, raw customer data, or overexposed logs into evidence.
- Prefer primary-source links and immutable identifiers.
- Preserve integrity hashes for generated evidence where practical.
- Call out stale, contradictory, unactionable, or self-attested evidence.
