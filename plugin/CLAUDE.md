# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. `AGENTS.md` is authoritative for repository structure, the 4-plugin split, build/test commands, and the safe regeneration procedure — read it first. This file adds Claude-Code-specific architecture notes and one regeneration caveat not covered there.

## Architecture Notes

- **Role selection** (`agents_select` tool call, part of `cadre`) routes tasks to specialist roles from the Cadre catalog. It returns a dispatch plan without invoking agents.
- **Lifecycle governance** (Agentic SDLC, part of the optional `cadre-lifecycle-core`/`-github`/`-gitlab` plugins) provides G1–G10 gates for governed delivery. Gate state and transitions live entirely in the external `agentic-sdlc` kernel — role selection in this repository does **not** execute gates; `bin/cadre select` calls `build_dispatch_plan.py` directly (no wrapper layer), and that script relays gate metadata the kernel already computed so a dispatch plan can be annotated with `required_quality_gates`/`human_gates`. Actual gate decisions are recorded through `bin/cadre sdlc` (a thin pass-through to the kernel), driven conversationally by the lifecycle plugins' skills.
- **Separation of concerns**: role selection (`cadre`) is fully independent of lifecycle gates (`cadre-lifecycle-core` and friends) — installable separately, usable separately. A task can be routed to roles without any lifecycle plugin installed, and vice versa.
- **Human approval invariant**: no agent or automation may approve its own work. This is enforced structurally in both role selection (independent reviewer) and lifecycle gates (separation of duties, checked by the external kernel — `decide`/`approve-from-github*`/`approve-from-gitlab*` all refuse a decision from a preparer or verifier of the same gate).

## Regeneration guard caveat

AGENTS.md and README.md's "Regenerating Assets" cover the safe procedure (regenerate into a scratch directory, diff, apply everything except the hand-authored exceptions). One additional caveat: this is currently a documentation-only safeguard. The register's `generate_global_plugin.py` guard against overwriting an existing `--output` target only checks for the *presence* of a `.codex-plugin/plugin.json`, and this repo has one (it is itself a packaged plugin) — so the guard does not actually stop `README.md` from being clobbered if `cadre generate-plugin --output` is run directly against this repository anyway. Tracked upstream at [deagy/cadre#97](https://github.com/deagy/cadre/issues/97), tracked here at [deagy/cadre-lifecycle#3](https://github.com/deagy/cadre-lifecycle/issues/3). Once a structural guard lands upstream, revisit whether this note is still needed.
