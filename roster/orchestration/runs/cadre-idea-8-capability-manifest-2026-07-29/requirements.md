# Requirements Baseline — Idea #8: Declarative Runner Capability Manifest

> **Provenance notice:** the original `requirements.md` written by `requirements-agent` on 2026-07-29 was deleted from disk by an unrelated concurrent session's git operation before it was committed. This file is a reconstruction, written by the orchestrating session from the dispatched agent's own detailed self-report (preserved in the orchestration transcript), not the verbatim original bytes. Treat it as a faithful summary of record — requirement IDs and rules below are as reported by the agent — not a byte-exact recovery. The actual shipped implementation (`agents/runner-capabilities.json`, `agents/runner-capabilities.schema.json`, `agents/orchestration/src/validate_runner_capabilities.py`) is the authoritative record of what was actually built; this document records intent/rationale.

**Task ID:** `cadre-idea-8-capability-manifest-2026-07-29`
**Agent:** `requirements-agent`, decomposing `product-intent.md` in this directory.

## Functional requirements (CM-FR-1..15)

- **CM-FR-1..4:** capability-tier (`CAPABILITY_PROFILES`) and model-tier (`ALLOWED_MODELS` / `ALLOWED_CODEX_MODELS` / `ALLOWED_REASONING_EFFORTS` / `TIER_MAP`) data belong in the manifest. Grounding found a 5th hand-copied location not counted in the original intent: `agents/catalog.schema.json`'s own enums.
- **CM-FR-5..8a:** 8 concretely enumerated structural runner-divergence facts from `runner-adapters.md` belong in the manifest: generated-wrapper existence, dispatch naming, peer/`communication_mode` support and gating, nested-team support, named-agent-dispatch support and workarounds, concurrency bounds. Narrative content stays prose in `runner-adapters.md` (Codex upstream-issue tracking, the ChatGPT-auth hypothesis, A2A rejection rationale, Cline SDK internals, Cline's PR-stack tracking, setup/fallback how-tos) — explicitly NOT moved into the manifest.
- **CM-FR-15:** Cline scope — represented only as absence-of-capability facts, no fabricated tools/sandbox grant (resolving OD-4).
- **CM-FR-13/14 (resolving OD-2):** no runtime consumer was found in `build_dispatch_plan.py`/`select_agents.py` that needs to read the manifest at agent-dispatch time — scoped to build-time/generator-only. Dispatch-time readability is a possible future extension, not baseline scope.
- **CM-FR-13/14 (generated-from vs. checked-against):** `CAPABILITY_PROFILES`/`ALLOWED_MODELS`/`ALLOWED_CODEX_MODELS`/`ALLOWED_REASONING_EFFORTS`/`TIER_MAP` are **generated from** the manifest (option (a): the manifest is the sole hand-edited source, Python constants are computed from it at import time — drift becomes structurally impossible rather than merely detected), not merely checked against it.
- **CM-FR-1..4 extension:** `agents/catalog.schema.json`'s enums are checked against the manifest (closing the 5th-location gap) rather than also generated from it, since that file has its own separate authoring precedent (idea #10).

## Non-functional requirements (CM-NFR-1..7)

Two-repo boundary preservation; generated output never hand-edited; no new parser dependency without cause (reuse idea #10's `jsonschema` precedent only in a guarded, non-required-path way, so `cadre generate-plugin`/`cadre select` stay dependency-free); fail-closed drift detection (CM-NFR-5); and — drawing directly on idea #10's own caught defect — a packaging-allowlist parity requirement (`generate_global_plugin.py::generate_suite_copy`'s file-selection list) so this doesn't repeat the exact `FileNotFoundError` packaging gap idea #10's review caught.

## Resolved open decisions

- OD-2: resolved — build-time/generator-only scope (see CM-FR-13/14 above).
- OD-3: resolved — concrete 8-fact structural/narrative split (see CM-FR-5..8a above).
- OD-4: resolved — Cline in scope only as absence-of-capability facts.
- OD-5 (format/location): carried forward as a design-phase-confirmable recommendation, not a hard decision — JSON file (`agents/runner-capabilities.json`) + Draft 2020-12 JSON Schema (`agents/runner-capabilities.schema.json`), reusing idea #10's `jsonschema` precedent; generated-but-committed, matching `agents/catalog.yaml`'s own precedent.
- OD-6: resolved — grounded current-state count stated (5 constants across 2 files, plus prose duplication in a 3rd) rather than a fabricated target.
- OD-7: resolved — drift-check is separable follow-up work in general, except a fail-closed comparison requirement (CM-NFR-5) is required in this baseline itself.

## Carried forward

- OD-1 (Product Owner): resolved 2026-07-29, see `product-intent.md`.

## Acceptance criteria (AC-1..AC-9)

1. AC-1: manifest artifact exists and is well-formed against its own schema.
2. AC-2: `CAPABILITY_PROFILES`/etc. are demonstrably generated-from, not hand-duplicated (a manifest edit propagates without touching Python source).
3. AC-3: single-edit-location walkthrough (change one value, one place, done).
4. AC-4: structural-fact coverage — all 8 enumerated facts present and correct.
5. AC-5: narrative content in `runner-adapters.md` is preserved, not deleted/moved.
6. AC-6: Cline scope is respected (absence-only, no fabricated grants).
7. AC-7: packaging-allowlist parity — demonstrated with a scratch-removal test proving the packaged copy would break if the allowlist entry were missing (matching idea #10's own caught bug class).
8. AC-8: fail-closed drift detection between the manifest and generated/derived Python constants.
9. AC-9: no fabricated quantitative metrics anywhere in the shipped artifact or docs.

## Ship-as / sequencing

No hard dependency on any in-flight backlog item — idea #3 and idea #10 have both shipped. Requirements baseline was ready to build immediately at time of writing.
