---
name: validate-agentic-sdlc
description: Validate a portable Agentic SDLC project overlay, dispatch plan, run record, gate sequencing, evidence bindings, and separation of duties. Use before lifecycle progression, release review, CI checks, plugin upgrades, or when diagnosing an invalid or incomplete Agentic SDLC configuration.
---

# Validate Agentic SDLC

1. Read repository instructions and `.agentic-sdlc/` configuration without changing lifecycle decisions.
2. Locate `../../scripts/agentic_sdlc.py`, run `validate --help`, then validate the requested project or record with supported flags.
3. Confirm schema versions, profile and kernel compatibility, stable IDs, exact artifact/environment bindings, gate order, evidence metadata, exception expiry, and invalidation history.
4. Confirm that authors, independent verifiers, and human approvers are distinct where required. Never repair missing approval evidence by assigning an agent or fabricating a person.
5. Confirm that every applicable lifecycle quality gate has sufficient evidence and that mutation-oriented `human_gates` remain separate and unsatisfied without explicit authority.
6. Treat `unknown` applicability, missing required evidence, stale approval, expired exception, self-approval, and undefined required extension semantics as blocking failures.
7. Report errors by file and record path, followed by warnings and the minimum safe remediation. Do not mark a gate approved as part of validation.
