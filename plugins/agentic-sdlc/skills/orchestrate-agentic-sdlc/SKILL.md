---
name: orchestrate-agentic-sdlc
description: Select and coordinate portable Agentic SDLC roles for product intake, design, delivery, release readiness, or runtime work. Use when a task needs a dispatch plan, independent specialist review, lifecycle gate tracking, traceability, or a project-owned run record.
---

# Orchestrate Agentic SDLC

A bare task description is enough to start; only ask the human when a value below
is genuinely undecidable from the prompt and repository. See
[`../../contracts/runner-adapters.md`](../../contracts/runner-adapters.md) for how
"ask the human" and "dispatch a subagent" map to the current runner, and for the
rule this skill depends on: **only this top-level orchestrator asks the human — a
dispatched subagent that hits a decision only a human can make must return a
blocking question instead of prompting directly.**

1. Read repository instructions and the complete `.agentic-sdlc/` project overlay. If the overlay is absent, invoke `initialize-agentic-sdlc` first (its default `quick` profile keeps this low-ceremony; heavier profiles remain available).
2. Derive plan inputs before asking for them:
   - **`--task`**: the user's prompt, verbatim or lightly scoped.
   - **`--task-id`**: a slug derived from the prompt plus today's date if the user didn't supply one; ask only if the run needs durable cross-session tracking and no ID convention exists in the repo.
   - **`--classification`**: the project's already-declared, most-conservative classification; ask only when a matched risk route is classification-sensitive and the prompt/repo leave it genuinely ambiguous.
   - **scope**: paths explicitly named in the prompt, else let the plan reflect the whole task description — don't require the user to enumerate files.
   - **execution mode**: default to planning-review-only unless the prompt clearly asks for changes to be made.

   Locate `../../scripts/agentic_sdlc.py`, run its `plan --help`, then generate a plan with the derived `--task-id` and `--task`.
3. Treat `required_quality_gates` as evidence-backed lifecycle decisions. Treat `human_gates` separately as authority stops for production, destructive work, persistent migrations, privileged identity changes, exceptions, or risk acceptance. Passing one never satisfies the other. A `quick`-profile plan will often carry no `required_quality_gates` at all — that's expected, not a defect; `human_gates` still apply.
4. If the plan is `needs-triage`, or any `human_gate`/mutation-gate applies, stop and ask the human directly — do not guess or silently narrow scope. Batch every question the plan and any dispatched agents raise into one turn rather than resolving them one at a time.
5. Dispatch bounded author and reviewer roles from the plan using the runner's subagent mechanism, giving each one its role definition, the task brief, and the instruction that it must return a blocking question rather than ask the human itself. Preserve independence: an author or material corrector cannot verify or approve that revision. Agents may prepare evidence but cannot impersonate named human authorities.
6. Maintain the project run record as the authoritative gate-state index. Bind outputs to stable IDs, exact revisions, evidence hashes, findings, exceptions, and re-entry history.
7. Stop affected progression when applicability, evidence, approval authority, or artifact identity is unknown. Return failed work to its responsible owner and invalidate dependent gates after material changes.
8. Validate the plan and run record. Report completed work, gate status, blockers, human decisions required, and the earliest re-entry gate.

Do not infer deployment authority or mutate a persistent environment unless the user separately authorizes the exact action.
