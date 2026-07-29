# Product Intent — Idea #6: Project-Local Routing Overlay

> **Provenance notice:** the original `product-intent.md` written by `product-intent-agent` on 2026-07-29 was deleted from disk by an unrelated concurrent session's git operation before it was committed. This file is a reconstruction, written by the orchestrating session from the dispatched agent's own detailed self-report (preserved in the orchestration transcript), not the verbatim original bytes. Treat it as a faithful summary of record, not a byte-exact recovery.

**Task ID:** `cadre-idea-6-routing-overlay-2026-07-29`
**Classification:** internal
**Repository:** `/home/deagy/sdk/cadre`
**Agent:** `product-intent-agent`

## Problem / why

`agents/orchestration/src/routing.py`'s `load_routing` reads `agents/orchestration/routing.yaml` as a single, non-overridable file. A consuming project's only customization path today is a full fork of the file, which forfeits upstream updates to routes, risk rules, and team recipes.

Idea #6 is the routing-configuration analogue of two mechanisms this suite already ships:
- The per-role shadow file (`.claude/agents/<role-id>.md` / `.codex/agents/<role-id>.toml`), documented in `.agents/skills/run-agent-orchestration/SKILL.md`.
- The `.agents/shared/` policy overlay (`agents/shared/README.md`, `cadre resolve-shared`).

`routing.yaml`'s array-of-entries shape doesn't map cleanly onto either precedent, so the mechanism shape was left as an open design question rather than picked in this intent record.

## Scope

Covers project-specific additions/adjustments to routes, risk-rule matching, and team recipes. The merged/effective configuration must stay verifiable by idea #1's orphan/coverage linter (`routing_health.py`) and idea #10's schema validator (`schema_validate.py` + `catalog.schema.json`/`routing.schema.json`) — both shipped by the time this intent was written (idea #10 was still on an unmerged branch at the time; it has since merged as PR #47).

## Exclusions (hard, not open)

No overlay-permitted weakening of safety-relevant routing structure — `human_gate`, required reviewers, `quality_gates` — mirroring `agent-autonomy.yaml`'s narrowing-only rule. Also excluded from this intent record: the actual overlay file format/merge algorithm, and re-litigating idea #1/#10's already-shipped scope.

## Success criteria

- SC-1: customization without forking.
- SC-2: survives upstream `routing.yaml` updates.
- SC-3: effective config stays covered by both existing checks (idea #1, idea #10).
- SC-4: no safety-field regression is possible via overlay.

## Open-decision register

- **OD-1 (blocking G1):** no named accountable Product Owner for this intent. *(Resolved 2026-07-29: the human directing this session accepted the Product Owner role for this and idea #8, matching the precedent set for idea #10.)*
- OD-2: overlay mechanism shape (shadow vs. deep-merge vs. additive vs. hybrid).
- OD-3: confirm idea #10 merges to `main` before idea #6 build sequencing. *(Resolved: idea #10 merged as PR #47 on 2026-07-29.)*
- OD-4: whether idea #1/#10's checks need extending to validate the *effective* merged config.
- OD-5: exact safety-boundary rule for what's overridable.
- OD-6: whether `knowledge_focus`/`change_intake`/`cross_stack` are in scope too.
- OD-7: whether to reuse `.agents/shared/`'s walk-up-to-`.git` discovery convention.

Knowledge retrieval was not used for this pass (ad hoc dispatch, consistent with the parent backlog document's own precedent), recorded explicitly per this suite's knowledge-use policy.
