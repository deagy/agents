# Cadre Feature Backlog — Requirements Baseline

**Task ID:** `cadre-feature-backlog-requirements-2026-07-28`
**Classification:** internal
**Repository:** `/home/deagy/sdk/cadre`
**Mode:** planning-review-only (no repository edits made during this phase)
**Agents dispatched:** `product-intent-agent` (framing pass, all 20 ideas), `requirements-agent` (formal decomposition, items A/B/C + grounded 17 one-liners)
**Knowledge retrieval:** not used for this ideation/requirements pass (ad hoc dispatch, not selector-driven — see note below)

This document is the orchestrator's synthesis of two independent agent outputs (orchestrator-relayed reconciliation — the agents did not communicate with each other). Where they disagree or one adds detail the other lacks, both are shown.

---

## Priority table (product-intent-agent framing, all 20 ideas)

| # | Idea | Priority | Beneficiary | Dependency |
|---|------|----------|-------------|------------|
| 1 | Routing coverage/orphan linter | P0 | Suite maintainers, all consumers | none (soft complement: #10) |
| 2 | Selection golden-corpus regression harness | P0 | Suite maintainers, routing reviewers | benefits from #1 |
| 3 | Agent-authoring restructuring (single source of truth) | P0 | Suite maintainers | sequence with #10 |
| 4 | Profile drift/re-sync report (`cadre profile diff`) | P1 | Consuming-project leads | none |
| 5 | Selection outcome telemetry (opt-in, local) | P2 | Suite maintainers | complements #2 |
| 6 | Project-local routing overlay | P1 | Consuming-project maintainers | follow #10; interacts with #1 |
| 7 | Provenance binding in dispatch plan | P1 | Auditors/reviewers | pairs with #8 |
| 8 | Declarative runner capability manifest | P1 | Plugin/generator maintainers | parallel to #3 |
| 9 | Enforced knowledge-store scope | P1 (→P0 at 2nd consumer) | Knowledge-store steward | steward sign-off required |
| 10 | Strict catalog/routing schema validation | P1 | Maintainers, reviewers | sequence after #3 |
| 11 | Role-discovery conversational skill | P2 | New/occasional users | soft: after #15 |
| 12 | Team-recipe dry-run visualizer | P2 | Recipe authors/debuggers | none |
| 13 | Adopt-cadre quickstart doc | P1 | New adopting projects | incorporate #4, #6 later |
| 14 | Committed sample `cadre select` output | P2 | Doc readers | reuse #2 fixture |
| 15 | Capability-filterable role index | P2 | Catalog browsers | soft: after #3 |
| 16 | Drift-detection CI badge in README | P2 | Prospective adopters | needs CI-platform decision (GitHub vs GitLab — flagged mismatch, see below) |
| 17 | Skills catalog page | P2 | Skill browsers | none |
| 18 | "Which runner am I in?" decision table | P2 | Multi-runner users | reuse #8 |
| 19 | Glossary cross-links | P2 | Doc readers | none |
| 20 | Consumer-facing changelog | P1 | Consuming-project leads | complements #4, #13 |

**Open flag from product-intent-agent:** idea #16 assumed a GitHub-hosted badge is needed since `team-profile.yaml.source_control.platform: github`, but `team-profile.yaml.cicd.platform: gitlab_ci` — these conflict for *this* repository. Not yet resolved; low priority (P2), not blocking current build.

---

## Deep requirements — Items A/B/C (moving to build)

### Item A — Routing coverage / orphan linter

**Grounding:** `routing.py`'s `load_routing`/`load_catalog` validate structure but never check that every catalog role is *reachable* via routes/risk_rules/team_recipes, nor that every routing-referenced agent ID exists in the catalog, across the *whole* file — only for agents actually selected by a given task at runtime (`build_dispatch_plan._validate_agents`).

**Functional requirements:** A-FR-1..8 — report catalog agents unreachable from any route/risk_rule/team_recipe/change_intake/cross_stack reference (A-FR-1); report routing-referenced agent IDs missing from the catalog (A-FR-2); name exact location per finding (A-FR-3); wired into `test_repository_health.py`-run suite (A-FR-4); **must count risk_rules and team_recipes as valid reachability paths, not routes-array only** — several real roles (`release-engineer`, `escalation-manager`, `threat-modeler`) are only reachable that way today (A-FR-5); read-only, no mutation (A-FR-6); passes clean on current repo state (A-FR-7); has a negative-fixture test proving it actually fails when it should (A-FR-8).

**Non-functional:** no change to selection behavior; <1s runtime; deterministic; reuse `routing.py`'s existing loaders (don't write a second parser); no dependency on `AGENTIC_SDLC_BIN`.

**Scope decision (assumed, not human-blocking):** v1 targets this repository's own routing.yaml only — does not need to reason about a future project-local overlay (idea #6). Ship as a new sibling module (`agents/orchestration/src/routing_health.py` + `agents/orchestration/test/test_routing_coverage.py`), **not** as edits inside the existing `test_repository_health.py`, to avoid file-ownership collision with item B.

**Acceptance criteria:** clean repo → 0 findings; fixture with one catalog agent stripped from all routing references → linter names that exact agent; fixture with a dangling route reference → linter names route ID + field + bogus agent ID; runs under the existing `unittest discover` invocation with no new command to teach CI; code review confirms it imports `routing.py`'s loaders rather than re-parsing.

### Item B — Selection golden-corpus regression harness

**Grounding:** no existing versioned (task, changed-files) → expected-selection fixture set exists; `test_selector.py`/`test_agents_dispatcher.py` test matching primitives, not end-to-end selection-shape regression.

**Functional requirements:** B-FR-1..7 — git-tracked fixture data file with task text, changed files, and expected `{primary, reviewers, support, matched_routes}` per case; harness calls `build_dispatch_plan()` in-process (no subprocess) and asserts equality; **on mismatch, reports the specific field delta**, not a generic assertion failure (B-FR-3); excludes/normalizes `generated_at`, `dispatch_fingerprint`, and knowledge_context (external-CLI-dependent) from comparison; initial corpus covers every existing route category + at least one fixed and one dynamic team-recipe trigger, reusing existing test cases where possible rather than duplicating; fixture updates are a single reviewable diff (data file, not inline Python literals); a fixture whose task/files no longer match anything (`needs-triage`) is itself a reportable failure, not a silent pass.

**Non-functional:** pure test-side addition, no production code changes; full corpus run in low seconds even as it grows; exclude run-to-run-variable fields from comparison (same pattern already used in `test_repository_health.py`).

**Design decision made explicit by requirements-agent (stated as assumption, not blocking):** exact-match assertion (expected set == actual set), not precision/recall scoring — simpler, matches existing test style. Zero-tolerance CI gating (any mismatch fails), consistent with how `test_repository_health.py`'s drift checks already behave — no quarantine/tolerance mechanism in v1.

**Ship as:** new file(s) — `agents/orchestration/test/test_selection_golden_corpus.py` + a fixtures data file — same file-ownership-isolation reasoning as A.

**Acceptance criteria:** runs under existing `unittest discover`; editing one route's `reviewers` in a scratch copy fails exactly the fixtures touching that route, naming the field delta; renaming a keyword an existing fixture depends on (without updating the fixture) fails with a clear "no match" signal; fixtures are data, not Python literals; a simulated "routing.yaml changed, fixture not updated" case is caught (demonstrated, not just claimed) as part of the implementing agent's own verification.

### Item C — Agent-authoring restructuring (single source of truth)

**This is explicitly the highest-blast-radius item** — touches all 47 `AGENT.md` files, `catalog.yaml`, `routing.yaml`'s `knowledge_focus` block, `routing.py`'s parser, `generate_global_plugin.py`, `test_repository_health.py`'s sync tests, and `CONTRIBUTING.md`/`RUNBOOK.md`.

**Functional requirements:** C-FR-1..9 — canonical location is `AGENT.md` frontmatter for `model`/`codex_model`/`reasoning_effort`/`knowledge_focus` at minimum; a generation step derives `catalog.yaml`'s fields and `routing.yaml`'s `knowledge_focus` entries from it; `capability`/`phase`/`definition` migration needs an explicit decision, not silent partial migration (C-FR-3); generation step supports `--check` mode matching existing `generate_authority_aides.py --check` / `generate_global_plugin.py --check` convention; **existing consumers (`routing.py` loaders, used by items A and B) must keep a stable parseable `catalog.yaml`-shaped artifact** — recommended: keep `catalog.yaml`'s current line-oriented shape and filename as a *generated* output (C-FR-6), which minimizes blast radius on A/B and avoids turning `routing.py`'s hand-rolled parser into a general YAML/frontmatter parser; existing sync tests continue to pass in *intent* (not weakened); `CONTRIBUTING.md`/`RUNBOOK.md` updated to describe the new workflow; **zero silent value changes** — every one of the 47 roles' current effective values must be preserved exactly through migration (C-FR-9), verified by diff.

**Non-functional:** zero selection-output drift for the full item-B golden corpus before/after migration (this is why B must exist *before* C is built); prefer extending `generate_global_plugin.py`'s existing generation pass over adding a third separate generator script unless there's a concrete reason not to; CI must fail-closed on frontmatter/derived-file drift; parser must not need to become general-purpose YAML.

**Open design decisions requirements-agent flagged as consequential but resolved as recommendations (not hard human blockers), which I'm surfacing to you before build starts given the 47-file blast radius:**
1. **Migration style:** incremental, role-by-role (dual-format transition period) rather than one atomic 47-file flag day — recommended, consistent with "make reversible, scoped changes."
2. **Frontmatter format:** YAML frontmatter (`---`-delimited), consistent with the suite's existing heavy YAML use — recommended, but confirm it doesn't collide with any runner-native frontmatter convention already read by Claude Code's own sub-agent format.
3. **`catalog.yaml`'s fate:** stays as a generated-but-committed artifact in its current shape (matches the existing precedent of `plugins/cadre/` being generated-but-committed) — recommended over having it disappear and consumers read AGENT.md frontmatter directly at runtime, which would be higher-risk and could break external consuming-project tooling that parses `catalog.yaml` directly.

**Ship as:** touches `test_repository_health.py`'s existing sync tests directly (unlike A/B) — sequenced *after* A and B land, both to avoid concurrent-edit collision on that file and so A's linter + B's corpus can serve as the automated correctness check for C's migration itself.

**Acceptance criteria:** generated output for all 47 roles matches pre-migration content exactly (or documented-equivalent); adding one new throwaway role end-to-end requires editing exactly one `AGENT.md` frontmatter block + running the generator (demonstrated); `--check` mode fails on unregenerated frontmatter edits, passes after regeneration; full existing test suite + A's linter + B's corpus all pass with zero selection drift; docs updated, no stale "hand-sync three files" instructions remain.

---

## Recommended build order

**A and B first, in parallel** (no file-level collision if both ship as new sibling files rather than editing `test_repository_health.py` directly) **→ then C.**

Rationale: A and B are the regression-insurance tools that let C's large mechanical migration be verified as behavior-preserving rather than manually eyeballed across 47 files. Building C first would mean designing A/B against a moving target and having no automated detector for a C-introduced regression until A/B were retrofitted afterward.

This matches the order you originally listed (routing linter, golden-corpus, agent-authoring) — no reordering needed.

---

## Remaining 17 backlog items — one-line acceptance criteria (grounded in actual code gaps, not the original ideation wording — see caveat)

1. Knowledge-focus completeness check — fails if a routed catalog agent lacks a `knowledge_focus` entry, checked statically not just at plan-build runtime.
2. Team-recipe membership validator — fails on any `team_recipes` member/role ID absent from the catalog, or `route_ids` absent from `routes`.
3. Quality-gate ID validator — fails on unrecognized Agentic SDLC gate IDs in route/risk-rule `quality_gates` when the kernel is available.
4. CLI `--top` boundary test — confirms rejection outside 1–20 with clear stderr.
5. Cross-platform wrapper parity — `bin/cadre`, `bin/cadre.ps1`, `plugins/cadre/bin/cadre` produce identical plans across POSIX/Windows.
6. Plugin version bump automation — atomic bump of both manifests or full rejection on partial failure.
7. Skill packaging completeness — every `SKILL.md`-referenced asset copied into `plugins/cadre/skills/`.
8. Codex bootstrap idempotency — unchanged source → zero filesystem writes on re-run.
9. Authority-aide generation drift check — `generate_authority_aides.py --check` fails on hand-edited aide files.
10. Dispatch-fingerprint stability — same inputs → same fingerprint across runs.
11. Secure-cloud profile subset consistency — profile's agents all present in the full catalog export.
12. MCP dispatch server parity — Codex MCP-dispatched role instructions match the direct `.toml` wrapper.
13. Risk-rule keyword-group conjunction test — partial keyword-group match doesn't trigger a multi-group risk rule.
14. Human-gate description completeness — every `human_gate` ID has a real description, not a generic fallback.
15. Origin-slug fallback determinism — stable `local-<basename>-<hash>` across repeated runs with no git remote.
16. Sample-reference leakage guard extension — generalizes the SAMPLE-001-specific scan to future sample artifacts.
17. Workflow-value/schema/file triangulation — extends the existing schema/file test to also confirm every workflow doc is reachable by at least one route/risk-rule (same "defined but unreachable" gap class as item A, for workflow docs).

**Caveat (requirements-agent's own flag):** items 1–17 above were grounded independently in the actual codebase rather than transcribed from the original 20-item ideation list (items 4–20 in the priority table above), since the two dispatches ran in parallel without shared context. Treat the priority table (idea 1–20, from product-intent-agent) as the authoritative backlog identity/naming, and this list as a secondary, code-grounded set of *additional* small-scope acceptance-criteria candidates uncovered during grounding — not a restatement of items 4–20.

---

## Disposition

- **Human gates reached:** none required to reach this point (all work was read-only planning).
- **Before build starts**, the orchestrator is asking you to confirm the three C-item design recommendations above (migration style, frontmatter format, catalog.yaml's generated-but-committed fate) given the 47-file blast radius — everything else in this requirements pass is being treated as a stated, reasonable assumption per each agent's own "label assumptions, don't block on derivable answers" instruction.
- **Next safe action:** dispatch design + build waves for A and B in parallel (new sibling files, no edit collision), reviewed by agents that did not author them; hold C until A and B are merged/verified.
