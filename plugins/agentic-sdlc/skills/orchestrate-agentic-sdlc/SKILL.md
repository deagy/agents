---
name: orchestrate-agentic-sdlc
description: Select and coordinate portable Agentic SDLC roles for product intake, design, delivery, release readiness, or runtime work. Use when a task needs a dispatch plan, independent specialist review, lifecycle gate tracking, traceability, or a project-owned run record.
---

# Orchestrate Agentic SDLC

1. Read repository instructions and the complete `.agentic-sdlc/` project overlay. If the overlay is absent, invoke `initialize-agentic-sdlc` first.
2. Locate `../../scripts/agentic_sdlc.py`, run its `plan --help`, then generate a plan with `--task-id` and `--task`. Put the objective, classification, scoped paths, constraints, and execution mode in the task text when relevant.
3. Treat `required_quality_gates` as evidence-backed lifecycle decisions. Treat `human_gates` separately as authority stops for production, destructive work, persistent migrations, privileged identity changes, exceptions, or risk acceptance. Passing one never satisfies the other.
4. Dispatch bounded author and reviewer roles from the plan. Preserve independence: an author or material corrector cannot verify or approve that revision. Agents may prepare evidence but cannot impersonate named human authorities.
5. Maintain the project run record as the authoritative gate-state index. Bind outputs to stable IDs, exact revisions, evidence hashes, findings, exceptions, and re-entry history.
6. Stop affected progression when applicability, evidence, approval authority, or artifact identity is unknown. Return failed work to its responsible owner and invalidate dependent gates after material changes.
7. Validate the plan and run record. Report completed work, gate status, blockers, human decisions required, and the earliest re-entry gate.

Do not infer deployment authority or mutate a persistent environment unless the user separately authorizes the exact action.
