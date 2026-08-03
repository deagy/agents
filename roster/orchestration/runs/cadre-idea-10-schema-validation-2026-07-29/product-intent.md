# Product Intent Record — Strict catalog/routing schema validation

**Intent ID:** `INTENT-CADRE-BACKLOG-10`
**Revision:** 1 (initial)
**Status:** draft — awaiting human Product Owner review at G1
**Author (agent):** product-intent-agent
**Date:** 2026-07-29
**Repository:** `/home/deagy/sdk/cadre`
**Classification:** internal
**Source backlog item:** `agents/orchestration/runs/cadre-feature-backlog-requirements-2026-07-28/requirements.md`, priority table row #10 ("Strict catalog/routing schema validation" — P1 — Beneficiary: Maintainers, reviewers — Dependency: sequence after #3). Priority (P1) and dependency sequencing were set by the prior product-intent-agent framing pass and are carried forward here as approved context, not re-decided by this record — see "Explicitly not decided here."

---

## 1. Owner

**Accountable Product Owner:** not named in any source document read for this record. `team-profile.yaml`'s `out_of_scope_standards` block names Daniel Eagy as Product Owner for a specific, unrelated compliance-scope decision (2026-07-26); nothing in the backlog, `AGENTS.md`, or `RUNBOOK.md` designates a Product Owner role for this repository's own feature backlog. This is logged as an open item in the decision register (OD-1) rather than assumed.

**Working owner for this intent record's authorship:** product-intent-agent (this agent), acting on the orchestrator's dispatch instruction that named idea #10 and its unblocked dependency. Authorship does not confer approval authority — see Authority section of this agent's role definition.

## 2. Users / beneficiaries

Restating the backlog's own beneficiary line, traced to concrete roles rather than left generic:

- **Suite maintainers** who hand-edit `agents/catalog.yaml` and `agents/orchestration/routing.yaml` directly (both files are edited by hand today; `catalog.yaml` is described elsewhere in this repo's planning artifacts as a candidate for becoming generated-but-committed output of item #3, but as of this record it and `routing.yaml` are both maintained by direct edit).
- **Reviewers** of pull requests that touch either file (per `routing.yaml`'s own `agent-suite-governance` route, this includes `code-reviewer` and `test-engineer`, with `application-engineer`/`debugging-engineer` as primary implementers of orchestration-layer changes).
- **Downstream code that consumes both files without re-validating them**: `agents/orchestration/src/routing.py`'s `load_catalog`/`parse_catalog_entries`/`load_routing`, `agents/orchestration/src/routing_health.py` (idea #1's linter, which calls those same loaders), `agents/orchestration/src/select_agents.py` / `build_dispatch_plan.py` (task-time selection), `agents/orchestration/src/generate_global_plugin.py` (plugin generation), and `agents/orchestration/test/test_repository_health.py` (the drift guard). All of these currently trust whatever `load_catalog`/`load_routing` hand back once those functions' own narrow checks pass.
- **Consuming projects** that read `catalog.yaml`/`routing.yaml` shapes from outside this repository (referenced in the item-C notes in the source requirements doc as a reason to keep `catalog.yaml`'s shape stable) are an indirect beneficiary of a stable, well-defined schema, though they are not this intent's primary audience.

## 3. Problem statement (WHAT and WHY)

`agents/catalog.yaml` and `agents/orchestration/routing.yaml` are both hand-edited, structurally significant configuration files with no formal schema. Today's only structural checking is:

- `agents/orchestration/src/routing.py`'s `load_routing()` — checks `version == 1`, that `routes` and `risk_rules` are lists, that route/risk-rule/team-recipe `id`s are globally unique, that `keyword_groups` (where present) are non-empty string lists, and that `dynamic` team-recipe `instances.min`/`max` are valid integers with `1 <= min <= max`. It does **not** validate `routes`/`risk_rules`/`team_recipes` field shapes beyond those specific checks (e.g. it does not confirm `primary`/`reviewers`/`support`/`paths`/`keywords`/`quality_gates`/`human_gate` are the right types, does not validate `cross_stack.route_ids` reference real routes, does not validate `change_intake` shape, does not validate `knowledge_focus` values).
- `agents/orchestration/src/routing.py`'s `load_catalog()`/`parse_catalog_entries()` — a hand-rolled line-oriented parser (`parse_keyed_entries`) that extracts only six known field names (`definition`, `phase`, `capability`, `model`, `codex_model`, `reasoning_effort`) per agent block and raises only on a duplicate id or an empty catalog. It does not check that `phase`/`capability`/`model`/`codex_model`/`reasoning_effort` hold one of their allowed enum values, that `definition` points to a file that exists, or that every expected field is present.
- `agents/orchestration/src/generate_role_metadata.py`'s `_validate_record()`/`ALLOWED_PHASES`/`TIER_MAP` — real enum/shape validation, but scoped only to the per-role metadata block it generates (`phase`, `model`↔`codex_model`↔`reasoning_effort` tier consistency) at generation time, not to the full `routing.yaml` shape (routes, risk_rules, team_recipes, change_intake, cross_stack) and not re-run as a standalone check against hand-edits made after generation.
- `agents/orchestration/src/routing_health.py` (idea #1, already shipped) checks a different property entirely: reachability/orphan-and-dangling-reference coverage between catalog and routing IDs. It presumes both files already parsed successfully and are internally well-typed; it is not a shape/type/enum validator and does not claim to be one.
- `agents/orchestration/test/test_repository_health.py` guards catalog/plugin/routing *generation* drift (i.e., "did you forget to regenerate"), not general schema conformance of hand-authored content.

**Consequence:** a malformed edit to either file — a typo'd YAML/JSON structural error, a wrong type (e.g. a string where a list is expected), a missing required key, an invalid enum value (e.g. an unrecognized `phase`, `model` tier, `communication_mode`, or gate ID), or an internally-inconsistent cross-reference not covered by idea #1's reachability check (e.g. `cross_stack.route_ids` naming a route ID that doesn't exist, a `team_recipes[].requires_route` naming a nonexistent route, a `human_gate` value with no corresponding description) — currently surfaces, if at all, only when some downstream code path happens to touch the specific malformed field at runtime (task selection, plugin generation, or an ad hoc test), with an error message shaped by whichever consumer tripped over it first rather than by a single authoritative schema. Some malformed shapes may not be caught by any current code path at all (see Open Decision OD-3). This is inconsistent, late-discovered, and not centrally testable as "is this file valid" independent of "does today's specific set of code paths happen to exercise the broken part."

**Desired outcome:** maintainers and reviewers get a single, authoritative, centrally-testable answer to "is `catalog.yaml` / `routing.yaml` structurally and type-valid" that runs the same way every time, independent of which specific downstream consumer would eventually have tripped over a given defect, and independent of which task happens to route through the broken field at runtime. This is explicitly a new, complementary layer — it sits alongside, and does not replace, idea #1's reachability linter or `test_repository_health.py`'s generation-drift guard, both of which check different properties (see Scope).

## 4. Scope

In scope for this intent (the *problem space* this backlog item addresses — not an implementation mandate):

- Formal, complete structural/type/enum validation of `agents/catalog.yaml`'s per-role fields (`definition`, `phase`, `capability`, `model`, `codex_model`, `reasoning_effort`, and any fields the eventual item-C frontmatter migration adds), extending today's narrow `generate_role_metadata.py`-time checks into a standalone, independently runnable validator.
- Formal, complete structural/type/enum validation of `agents/orchestration/routing.yaml`'s full documented shape: `version`, `change_intake` (`keywords`, `agents`, `quality_gates`), `routes[]` (`id`, `paths`, `keywords`, `keyword_groups`, `primary`, `reviewers`, `support`, `quality_gates`), `risk_rules[]` (same fields plus `human_gate`), `cross_stack` (`route_ids`, `minimum_matches`, `support`), `team_recipes[]` (`id`, `type`, and the fixed-vs-dynamic-specific fields: `route_ids`/`minimum_matches`/`members`/`minimum_members_selected` for `fixed`, `role`/`instances`/`requires_route` for `dynamic`, plus shared `communication_mode`/`fallback`/`description`), and `knowledge_focus` (map of agent id → description string).
- A validation failure mode that is deterministic, locates the exact offending field/index (matching this repo's existing convention, e.g. `routing_health.py`'s `structural_location` pointers and `test_repository_health.py`'s precise-mismatch reporting style), and is runnable standalone (not only as a side effect of some other operation) so it can be wired into CI and into local pre-submit checks the same way `test_repository_health.py` and `routing_health.py` already are.
- Coverage of both files' *current* documented shape as evidenced by their current content and by `routing.py`/`generate_role_metadata.py`'s existing partial checks — this record does not invent new fields or shapes beyond what already exists or is already planned (e.g. item #3's frontmatter-derived fields).

## 5. Exclusions (explicitly out of scope for this intent)

- **Implementation approach is not decided here.** Whether to use a schema-description language (e.g. JSON Schema, given `agents/orchestration/selection.schema.json` already exists in this repo as a precedent) versus a hand-written validator function versus a typed-model library (e.g. pydantic) versus extending `routing.py`'s existing hand-rolled parser is a requirements/design decision, not a product-intent decision, per this role's authority limits. See Open Decision OD-2.
- **Reachability/orphan/dangling-reference checking is not re-scoped here.** That is idea #1, already shipped as `routing_health.py`. This intent explicitly treats it as a separate, complementary check and does not propose merging, replacing, or duplicating it.
- **Generation-drift checking (`test_repository_health.py`'s existing role) is not re-scoped here.** Schema validity ("is this shape legal") and generation-sync ("does hand-edited/generated content match its source of truest") are different questions; this intent does not propose collapsing them into one check.
- **The eventual item-C (agent-authoring restructuring) frontmatter schema itself is not this intent's subject.** Item #3 has already shipped per the dispatch context; this intent covers validating `catalog.yaml`/`routing.yaml` as they exist post-#3, not re-litigating #3's frontmatter design.
- **No decision on whether validation blocks CI, blocks local commits, or is advisory-only.** That is a scope/priority/process decision for requirements or design, not intent.
- **No decision on whether/how a project-local routing overlay (backlog idea #6, explicitly sequenced *after* this idea) would be validated.** Idea #6 is a downstream dependency of #10, not a concern this intent needs to resolve now; a schema validator built for this repo's own files should not be assumed compatible with overlay semantics that do not exist yet.
- **No performance, tooling-installation, or dependency-selection commitments.** Whether a schema-validation library becomes a new dependency (subject to `library-standards.yaml`'s justification-for-new-dependency rule) is a downstream design question.

## 6. Constraints

Traced to existing approved repository policy and code, not invented:

- **C-1 (repo-wide, `AGENTS.md`/`CLAUDE.md`/RUNBOOK.md convention):** any new automated check must be runnable under the existing `python3 -m unittest discover` invocations already documented for this repository (`agents/orchestration/test/`), consistent with how idea #1 (`routing_health.py`) and item A/B were required to ship as "no new command to teach CI."
- **C-2 (from item C's stated non-negotiable, `requirements.md` line 75):** any validator must keep `catalog.yaml` consumable by `routing.py`'s existing loaders as a stable, parseable artifact — this intent does not authorize turning `routing.py`'s parser into a general-purpose YAML/frontmatter parser as a side effect of adding schema validation, though the requirements/design phase may decide the schema validator is a distinct module from `routing.py` entirely.
- **C-3 (`library-standards.yaml`):** any new dependency required for schema validation needs documented technical rationale, pinned version, license review, and vulnerability/supply-chain review before adoption — not assumed in scope for this intent record.
- **C-4 (this role's authority limit):** this record may not mandate JSON Schema vs. hand-written validator vs. pydantic vs. extending `routing.py`; it may only state the problem, desired outcome, and flag the tradeoff as open.
- **C-5 (`agents/shared/operating-principles.md`):** the check itself, once built, must produce evidence-based, precisely located findings (field + index, matching existing repo convention) rather than generic pass/fail — inherited from the same convention idea #1 and item B were held to.
- **C-6:** must not weaken, replace, or silently subsume `routing_health.py` (idea #1) or `test_repository_health.py`'s existing drift checks — per `agents/shared/operating-principles.md`'s "do not silently weaken tests... or approval gates."

## 7. Environments

This is a repository-tooling change with no runtime/deployment environment of its own: it affects local developer workflow (pre-submit validation) and CI (`gitlab_ci` per `team-profile.yaml`, noting the same GitHub-vs-GitLab flag already logged against idea #16 applies generally to this repo's CI platform identity — not re-litigated here). It does not touch Proxmox, Talos, Kubernetes, or any production/staging surface; `agent-autonomy.yaml`'s `mutations` approval tiers for persistent/staging/production environments do not apply to this backlog item's scope.

## 8. Assumptions

Labeled explicitly per this role's required behavior, distinguished from approved fact:

- **A-1:** Idea #3 (agent-authoring restructuring) having "shipped" per the dispatch context means `catalog.yaml`/`routing.yaml`'s current on-disk shape, as read for this record on 2026-07-29, is the shape this intent should validate against — not a hypothetical future shape. This record does not independently re-verify item C's acceptance criteria (e.g. "zero silent value changes... verified by diff") were met; it takes the dispatch instruction's "just shipped" framing as given context, not as an approved fact this agent re-audited.
- **A-2:** The backlog's P1 priority and "sequence after #3" dependency for idea #10, and idea #10's placement in the existing priority table, remain valid as prior product-intent-agent framing from 2026-07-28 and are not re-decided here (see "Explicitly not decided here").
- **A-3:** "Strict" in the backlog title is read as "complete/authoritative for the documented shape," not as a specific enforcement mechanism (e.g. not read as mandating a fail-closed CI gate versus advisory warnings) — that enforcement-mode question is logged as OD-4, not assumed.

## 9. Conflicts

No conflicting objectives were found between this intent and other read sources. One adjacent, previously-logged, unrelated conflict is noted for completeness since it touches the same backlog: idea #16 flagged a `team-profile.yaml` mismatch between `source_control.platform: github` and `cicd.platform: gitlab_ci`; that conflict is orthogonal to idea #10's schema-validation subject matter and is not re-opened here, only cross-referenced.

## 10. Success criteria (measurable, not target-inventing)

Per this role's constraint against inventing targets/commitments/priorities, these are framed as observable conditions the eventual requirements/design/build phases can verify against, not as pass/fail numeric SLAs this record is authorized to set:

- **SC-1:** A hand-edit to `catalog.yaml` or `routing.yaml` that introduces a structural defect not caught by any of today's existing checks (`routing.py`'s narrow checks, `generate_role_metadata.py`'s per-role validation, `routing_health.py`'s reachability check, `test_repository_health.py`'s drift check) is detected by the new validator, with the finding naming the specific field/index — demonstrable via a negative fixture, matching the existing repo convention (idea #1's Item A acceptance criteria required an analogous negative-fixture proof).
- **SC-2:** The current, unmodified `catalog.yaml` and `routing.yaml` pass the new validator with zero findings (a clean baseline), demonstrating it does not introduce false positives against today's approved content.
- **SC-3:** The validator is runnable standalone, independent of any specific task-selection invocation (`build_dispatch_plan`) or plugin-generation invocation (`generate_global_plugin`) — i.e., "is this file schema-valid" is answerable without exercising unrelated code paths.
- **SC-4:** The validator's existence does not require modifying `routing_health.py` or `test_repository_health.py`'s existing checks to keep passing — it is additive, not a replacement (traced to constraint C-6).
- **SC-5:** Every enum-constrained field this record identified in Scope (`phase`, `model`/`codex_model` tiers, `communication_mode`, `team_recipes[].type`, and any `human_gate`/quality-gate ID cross-references the requirements/design phase decides are in scope) has at least one documented allowed-value set the validator checks against, sourced from existing code (e.g. `ALLOWED_PHASES`, `TIER_MAP`) rather than newly invented by this record.

Numeric targets (e.g. runtime budget, specific CI gating behavior) are intentionally not set here — they are a requirements/design decision per this role's constraint against inventing commitments.

## 11. Open-decision register

| ID | Decision needed | Accountable owner | Status | Notes / linked source |
|----|------------------|--------------------|--------|------------------------|
| OD-1 | Name the accountable Product Owner for this repository's own feature backlog (not just the unrelated 2026-07-26 compliance-scope decision) | Human — unnamed | **Blocking G1 approval** | No source document names this role for Cadre's own backlog; escalating per this role's "accountable Product Owner is unknown" trigger. |
| OD-2 | Implementation approach: schema-description language (e.g. extend the existing `agents/orchestration/selection.schema.json` precedent with catalog/routing schemas) vs. hand-written validator function vs. typed-model library (e.g. pydantic) vs. extending `routing.py`'s hand-rolled parser | Requirements/design phase (requirements-agent, then implementing engineer + code-reviewer) | Open, non-blocking for intent | Explicitly out of this role's authority (C-4). |
| OD-3 | Full enumeration of exactly which structural gaps existing code (`routing.py`, `generate_role_metadata.py`, `routing_health.py`) leaves uncovered, versus this record's Section 3 list, which was derived from reading the code but not exhaustively fuzz-tested against every field | Requirements-agent, as part of formal decomposition | Open, non-blocking for intent | This record names known gaps (e.g. `cross_stack.route_ids` reference validity, `team_recipes[].requires_route` reference validity, full `routes`/`risk_rules` field-shape checking) but does not claim the list is exhaustive. |
| OD-4 | Enforcement mode: fail-closed CI gate (matching `test_repository_health.py`'s and item B's zero-tolerance precedent) vs. advisory-only vs. staged rollout | Requirements/design phase; ultimately Product Owner once named (OD-1) | Open, non-blocking for intent | Assumption A-3 flags this as read loosely from "strict" in the backlog title. |
| OD-5 | Whether the eventual validator should also cover `agents/orchestration/selection.schema.json` itself (the dispatch-plan output schema) or is scoped strictly to the two *input* config files (`catalog.yaml`, `routing.yaml`) named in the backlog title | Requirements-agent | Open, non-blocking for intent | The backlog title says "catalog/routing schema validation," which this record reads as scoped to those two files' own shape, not the plan-output schema — but the existing `selection.schema.json` precedent makes this worth an explicit requirements-phase confirmation rather than silent assumption. |

## 12. Knowledge retrieval status

Not used for this pass. Consistent with the prior product-intent-agent framing pass for the same backlog (`requirements.md` header: "Knowledge retrieval: not used for this ideation/requirements pass (ad hoc dispatch, not selector-driven)"), this dispatch was likewise ad hoc rather than selector-driven, so no pre-dispatch retrieval occurred per `knowledge-use-policy.md`. No material decision in this record depends on unavailable or conflicting knowledge-store content — all claims here trace to files read directly from the repository (cited by path throughout). Follow-up retrieval remains available if a future revision of this record needs it.

---

## Handoff

This record is ready for G1 Intent Gate review by the (currently unnamed — see OD-1) human Product Owner. It is not ready for requirements decomposition to begin treating OD-2–OD-5 as resolved; those remain open decisions for the requirements/design phase to carry forward and, where relevant, escalate further.
