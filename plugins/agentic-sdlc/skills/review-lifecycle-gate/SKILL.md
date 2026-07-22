---
name: review-lifecycle-gate
description: Prepare an independent assessment of a specific Agentic SDLC lifecycle gate against its criteria, evidence, applicability, revision bindings, and authority requirements. Use when a gate is ready for review, needs-information, request-changes, blocked, or being prepared for a human decision.
---

# Review Lifecycle Gate

1. Read repository instructions, the full `.agentic-sdlc/` overlay, the task run record, and the selected gate's referenced evidence.
2. Verify prerequisite gate states, applicability, exact revision/artifact/environment bindings, provenance, evidence hashes, findings, exceptions, and required re-entry behavior.
3. Remain independent. If you authored or materially corrected the reviewed revision, stop and request another verifier. Never act as the human approver.
4. Run `py -3 <plugin-root>/scripts/agentic_sdlc.py validate --help`, then validate the record using supported flags. Use the CLI `status` command when it helps summarize current state.
5. Distinguish the lifecycle quality-gate assessment from any mutation-oriented `human_gates`. A positive quality review does not authorize production, destructive work, persistent migrations, privileged identity changes, risk acceptance, or exceptions.
6. Fail closed on unknown applicability, missing or stale evidence, identity mismatch, expired exceptions, unresolved blocking findings, or undefined required semantics.
7. Return `ready-for-human-decision`, `request-changes`, `needs-information`, or `blocked`; list evidence examined, findings, responsible owners, required human authority, and earliest re-entry gate. Do not record `approved` without authentic human approval evidence.
