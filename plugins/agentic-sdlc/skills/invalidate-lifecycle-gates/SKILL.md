---
name: invalidate-lifecycle-gates
description: Record a material project change and invalidate the earliest affected Agentic SDLC gate plus its dependent downstream gates. Use after requirement, architecture, implementation, evidence, artifact, environment, approval, exception, or deployed-configuration changes that may make prior lifecycle decisions stale.
---

# Invalidate Lifecycle Gates

1. Read repository instructions, `.agentic-sdlc/`, the authoritative run record, and evidence for the proposed change.
2. Identify the earliest affected gate from traceability and materiality; do not choose a later gate merely to preserve approvals. If impact is uncertain, fail closed at the earliest plausibly affected gate and record the uncertainty.
3. Locate `../../scripts/agentic_sdlc.py`, run `invalidate --help`, then invoke `invalidate` with `--task-id`, `--earliest-gate`, `--reason`, and the accountable `--actor`. Include the affected revision and change detail in the reason when relevant.
4. Ensure the record preserves prior decisions, invalidation timestamp, actor, reason, affected bindings, downstream invalidations, and required re-entry gate. Never delete approval history.
5. Do not substitute an agent for a human authority and do not reuse approval evidence across changed revisions, artifacts, environments, or expired windows.
6. Keep lifecycle quality-gate invalidation distinct from mutation-oriented `human_gates`; invalidating quality evidence neither authorizes nor performs a deployment, rollback, destructive action, or persistent migration.
7. Run CLI validation and report the change, invalidated gates, retained audit history, responsible artifact owner, and next required decision.
