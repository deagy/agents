# Product Intent — Idea #8: Declarative Runner Capability Manifest

> **Provenance notice:** the original `product-intent.md` written by `product-intent-agent` on 2026-07-29 was deleted from disk by an unrelated concurrent session's git operation before it was committed. This file is a reconstruction, written by the orchestrating session from the dispatched agent's own detailed self-report (preserved in the orchestration transcript), not the verbatim original bytes. Treat it as a faithful summary of record, not a byte-exact recovery.

**Task ID:** `cadre-idea-8-capability-manifest-2026-07-29`
**Classification:** internal
**Repository:** `/home/deagy/sdk/cadre`
**Agent:** `product-intent-agent`

## Problem / why

Runner-capability, tool-grant, sandbox-mode, and model-tier data lived in multiple independently-maintained places with no shared source of truth: `CAPABILITY_PROFILES` in `generate_global_plugin.py`; `ALLOWED_MODELS` / `ALLOWED_CODEX_MODELS` / `ALLOWED_REASONING_EFFORTS` / `TIER_MAP` in `generate_role_metadata.py`; prose in `.agents/skills/run-agent-orchestration/references/runner-adapters.md` (peer-vs-orchestrator-relayed team dispatch, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, Codex's `spawn_agent` named-dispatch limitation, Cline's lack of a generated wrapper); and the generated plugin output itself. Changing a capability tier, adding a runner, or changing a runner constraint meant editing Python in multiple files plus unlinked prose, with no drift check comparable to `test_repository_health.py`'s catalog/plugin guard. This is the same class of implicit-to-explicit move idea #10 (`agents/catalog.schema.json`) already made for role/routing data, applied here to runner/capability data instead.

## Scope

In-scope: `CAPABILITY_PROFILES`, the `ALLOWED_*` / `TIER_MAP` constants, and candidate structural (non-narrative) facts from `runner-adapters.md`.

## Exclusions

Deciding artifact format/location, whether existing Python constants get replaced vs. generated-from vs. left parallel, precise capability-concept definition, whether Cline must be represented now, and any drift-check implementation — all deferred to requirements/design.

## Owner

Not named in the source backlog or `team-profile.yaml` — recorded as OD-1, blocking G1 as originally written. *(Resolved 2026-07-29: the human directing this session accepted the Product Owner role for this and idea #6, matching the precedent set for idea #10.)*

## Success criteria

Verifiability-based rather than a fabricated numeric target:
- a single authoritative artifact exists;
- generator constants are generated-from-or-checked-against it;
- a single-artifact-edit walkthrough is possible (change one value, one place, done);
- no orphaned uncheckable prose copy remains.

## Open-decision register

- **OD-1 (blocking G1):** no named owner. *(Resolved, see above.)*
- **OD-2** (most consequential): whether the manifest is meant to be dispatch-time-readable (an agent introspecting its own grants), a build-time/generator-only concern (programmatically asking what a runner supports), or both.
- OD-3: narrative vs. structural boundary within `runner-adapters.md`.
- OD-4: whether Cline must be represented now.
- OD-5: format/location — explicitly out of this role's authority, deferred to requirements/design.
- OD-6: whether to set a quantitative target later.
- OD-7: sequencing relative to a future drift check.
