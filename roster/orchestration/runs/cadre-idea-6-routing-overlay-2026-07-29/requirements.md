# Requirements Baseline — Idea #6: Project-Local Routing Overlay

> **Provenance notice:** the original `requirements.md` written by `requirements-agent` on 2026-07-29 was deleted from disk by an unrelated concurrent session's git operation before it was committed. This file is a reconstruction, written by the orchestrating session from the dispatched agent's own detailed self-report (preserved in the orchestration transcript), not the verbatim original bytes. Treat it as a faithful summary of record — requirement IDs and rules below are as reported by the agent — not a byte-exact recovery. The actual shipped implementation (`agents/orchestration/src/routing_overlay.py`, `agents/orchestration/test/test_routing_overlay.py`) is the authoritative record of what was actually built; this document records intent/rationale.

**Task ID:** `cadre-idea-6-routing-overlay-2026-07-29`
**Agent:** `requirements-agent`, decomposing `product-intent.md` in this directory.

## Functional requirements (RO-FR-1..18)

- **Discovery/precedence (RO-FR-1, RO-FR-2):** reuse `agents/shared/src/resolve.py`'s walk-up-to-`.git` discovery convention; fail closed on a malformed overlay; no overlay present → effective config is byte-identical to the base file.
- **Per-section merge rules (RO-FR-3..12):**
  - `routes[]` / `risk_rules[]`: additive by non-colliding `id`, plus widen-only (append-only) edits to an existing base entry's matching conditions (`keywords` / `keyword_groups` / `paths`).
  - `team_recipes[]`: fully additive; base entries immutable.
  - `change_intake` / `cross_stack`: additive-only, with `cross_stack.minimum_matches` narrowing-only numerically.
  - `knowledge_focus`: ordinary deep-merge (purely descriptive, no restriction).
  - `ignored_gates`: can only shrink, never grow.
  - `version`: fixed contract field, cannot be overridden.
- **Safety-boundary (RO-FR-13..15, resolving OD-5):** widen-only matching-condition rules apply to *every* base entry, not only ones with an explicit `human_gate` — narrowing a base risk-rule's match conditions is functionally equivalent to stripping its `human_gate`/reviewers even without touching those fields directly, since a rule that never matches can never fire its gate. Additive-only entry merge (never whole-array replace) means an overlay-added weak rule can never suppress an already-matching base rule, since matches are unioned, not replaced.
- **Idea #1/#10 compatibility (RO-FR-16, RO-FR-17, resolving OD-4):** no new validator code needed — both `routing_health.py::run()` and `schema_validate.py::run()` already accept explicit `--routing`/`--catalog` path arguments, so pointing them at a materialized effective-config file works without modification to either file.

## Resolved open decisions

- OD-2 (mechanism shape): resolved as the per-section rules above (additive/widen-only/deep-merge, varying by section) — a requirements-level default, design-confirmable.
- OD-4: resolved — zero code changes needed to idea #1/#10's existing tools.
- OD-5: resolved — field-by-field safety boundary above, including the interaction-level narrowing-bypass gap.
- OD-6: resolved — all three of `change_intake`, `cross_stack`, `knowledge_focus` are in scope, each with its own rule (see per-section rules above).
- OD-7: resolved — reuse the existing `agents/shared/src/resolve.py` discovery convention rather than inventing a fourth one.

## Carried forward / newly surfaced

- OD-1 (Product Owner): resolved 2026-07-29, see `product-intent.md`.
- OD-3: idea #10 has since merged (PR #47) — no longer a blocker.
- **G-1 (new gap surfaced):** `ignored_gates` — a real safety-relevant field never named in the intent record's original scope — is now explicitly covered by RO-FR-12.
- **G-2, G-3 (carried forward, design-phase):** exact overlay file location/name; whether materialization happens at commit-time (drift-checked) vs. per-invocation.
- **G5 Security applicability:** flagged `unknown`-but-non-blocking in the original pass — requires explicit `security-reviewer` sign-off before this ships, per the intent record's own note. Not self-cleared.

## Acceptance criteria (AC-1..AC-9)

1. AC-1: no-overlay baseline — effective config byte-identical to base `routing.yaml`.
2. AC-2: add a new route via overlay.
3. AC-3: adjust an existing base route/risk-rule's matching conditions (widen-only).
4. AC-4: add a new team recipe via overlay.
5. AC-5: `id` collision between overlay and base entry is rejected.
6. AC-6: direct attempt to remove/weaken a safety field (`human_gate`, `reviewers`, `quality_gates`) on a base entry is rejected.
7. AC-7: narrowing-bypass rejection — an overlay that narrows a base risk-rule's matching conditions (without touching `human_gate` directly) is rejected. The key interaction-level test.
8. AC-8: idea #1 and idea #10 compatibility — `routing_health.py` and `schema_validate.py`, unmodified, both run cleanly against a materialized effective config.
9. AC-9: additive behavior demonstrated for `change_intake` / `cross_stack` / `knowledge_focus`.

## Ship-as / sequencing

Not hard-blocked on any other in-flight item once idea #10 merges (it has, as PR #47). Requirements baseline was ready to build immediately at time of writing.
