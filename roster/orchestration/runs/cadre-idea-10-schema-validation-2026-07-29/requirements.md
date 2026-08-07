# Requirements Baseline — Idea #10: Strict catalog/routing schema validation

**Requirements ID:** `REQ-CADRE-BACKLOG-10`
**Revision:** 1 (initial)
**Status:** draft — ready for G2 Requirements Baseline Gate review (pending G1 approval of the intent record this baseline decomposes)
**Author (agent):** requirements-agent
**Date:** 2026-07-29
**Repository:** `/home/deagy/sdk/cadre`
**Classification:** internal
**Decomposes:** `INTENT-CADRE-BACKLOG-10` (`agents/orchestration/runs/cadre-idea-10-schema-validation-2026-07-29/product-intent.md`), Revision 1

---

## 0. Grounding correction carried forward from code inspection (read this before the requirement tables)

The intent record's Section 3 (Problem statement) and Users/beneficiaries section frame `catalog.yaml` as "hand-edited" like `routing.yaml`, noting only that it "is described elsewhere ... as a candidate for becoming generated-but-committed output of item #3." Direct inspection of the current repository state (2026-07-29, after A-1's "item #3 has shipped" framing) shows this has already happened and materially narrows this baseline's scope for `catalog.yaml`:

- `agents/orchestration/src/generate_role_metadata.py` now **generates** `catalog.yaml` in full (`render_catalog`) from every `AGENT.md`'s frontmatter, and **splices** `routing.yaml`'s `knowledge_focus` block (`splice_knowledge_focus`) from the same source — `routing.yaml`'s `routes`/`risk_rules`/`team_recipes`/`change_intake`/`cross_stack`/`ignored_gates`/`version` remain hand-authored.
- `generate_role_metadata.py`'s `_validate_record()` already performs real, fail-closed, per-role enum/shape/tier-consistency validation (`phase`, `capability`, `model`, `codex_model`, `reasoning_effort`, `knowledge_focus` non-empty) at generation time, sourced from `ALLOWED_PHASES` (this file) and `ALLOWED_MODELS`/`ALLOWED_CODEX_MODELS`/`ALLOWED_REASONING_EFFORTS`/`CAPABILITY_PROFILES` (imported from `generate_global_plugin.py`).
- `agents/orchestration/test/test_repository_health.py::test_role_metadata_files_are_generated_and_in_sync` already runs `generate_role_metadata.py --check` in the existing `unittest discover` suite, so a hand-edit to `catalog.yaml` (or to `routing.yaml`'s `knowledge_focus` block) that drifts from regenerated content — including one that would have failed `_validate_record`'s enum checks had it come from frontmatter — already fails CI today, **but as an undifferentiated content-mismatch ("stale"), not as a field-precise validation finding**, and only when the corresponding `AGENT.md` frontmatter is available to regenerate against.
- `test_repository_health.py::test_catalog_definitions_and_agent_files_stay_in_sync` already confirms every `catalog.yaml` `definition:` value resolves to a real `AGENT.md` file.

**Consequence for scope:** this baseline's net-new work is concentrated on `routing.yaml`'s `routes`/`risk_rules`/`team_recipes`/`change_intake`/`cross_stack`/`ignored_gates` shape (none of which is generated or otherwise structurally validated beyond `load_routing()`'s narrow checks today) plus a **standalone** re-validation of `catalog.yaml`'s per-role fields that does not depend on `AGENT.md` frontmatter being present or regenerable — needed because (a) the intent record's own beneficiary list names external consuming projects that read `catalog.yaml` without access to this repository's `AGENT.md` sources, and (b) today's frontmatter-diff check reports "stale," not "field X on role Y has invalid value Z." This is recorded as **Gap G-1** in the gap register (Section 8) rather than silently narrowing the intent's stated scope.

---

## 1. Traceability — intent to requirements

| Intent section | Requirement(s) |
|---|---|
| §4 Scope, bullet 1 (catalog.yaml per-role fields) | SV-FR-1 .. SV-FR-6 |
| §4 Scope, bullet 2 (routing.yaml full shape) | SV-FR-7 .. SV-FR-24 |
| §4 Scope, bullet 3 (deterministic, location-precise, standalone failure mode) | SV-FR-25, SV-FR-26, SV-NFR-1, SV-NFR-2 |
| §4 Scope, bullet 4 (no new shapes invented) | SV-FR-1 .. SV-FR-24 (all sourced from current file content or existing code, cited per-requirement) |
| §5 Exclusion (implementation approach open — OD-2) | Carried forward unresolved, see §6 |
| §5 Exclusion (idea #1 not re-scoped) | SV-NFR-4, C-6 traceability in §7 |
| §5 Exclusion (`test_repository_health.py` role not re-scoped) | SV-NFR-4 |
| §5 Exclusion (item #3 frontmatter design not re-litigated) | SV-FR-1..6 validate `catalog.yaml`'s current shape only, not frontmatter |
| §5 Exclusion (CI/commit/advisory enforcement mode undecided — OD-4) | Carried forward unresolved, see §6 |
| §5 Exclusion (idea #6 overlay compatibility not assumed) | SV-NFR-6 |
| §5 Exclusion (dependency/perf commitments deferred) | SV-NFR-3, SV-NFR-5, §6 OD-2 |
| §6 C-1 (runnable under `unittest discover`) | SV-NFR-1 |
| §6 C-2 (`catalog.yaml` stays loader-parseable; no general YAML/frontmatter parser as a side effect) | SV-NFR-3 |
| §6 C-3 (new-dependency justification) | §6 OD-2, §9 |
| §6 C-4 (this record may not mandate implementation approach) | §6 OD-2 left open |
| §6 C-5 (evidence-based, precisely located findings) | SV-FR-25, SV-FR-26 |
| §6 C-6 (must not weaken/replace idea #1 or drift-guard) | SV-NFR-4 |
| §10 SC-1 .. SC-5 | AC-1 .. AC-8 (§5) |
| §11 OD-1 .. OD-5 | §6 (all carried forward, unresolved) |

## 2. Traceability — requirements to controls / tests / evidence

| Requirement group | Control / policy trace | Planned verifier | Evidence obligation |
|---|---|---|---|
| SV-FR-1..6 (catalog.yaml) | `agents/shared/operating-principles.md` "evidence-based, precisely located findings"; C-2 loader-stability | Negative-fixture unit test (new validator module) + `test_repository_health.py` regression | Passing test log naming the specific fixture/field per finding; clean-baseline run against current `catalog.yaml` |
| SV-FR-7..24 (routing.yaml) | Same, plus C-6 (additive to idea #1/drift guard) | Negative-fixture unit test (new validator module); must coexist with `routing_health.py` and `test_repository_health.py` runs in the same `unittest discover` pass | Same as above, plus a demonstration run showing `routing_health.py` and `test_repository_health.py` are unmodified and still pass |
| SV-FR-25, SV-FR-26 (error reporting) | C-5 | Fixture asserting exact finding text/location string | Finding text captured in test assertions (not just "raises") |
| SV-NFR-1..6 | C-1, C-2, C-6, `library-standards.yaml` | `unittest discover` invocation; code review | Test-suite pass output; code-review note confirming no new parser/dependency was added without justification |

## 3. Functional requirements — catalog.yaml (standalone, frontmatter-independent)

Grounding: `agents/catalog.yaml` (47 role blocks read 2026-07-29), `agents/orchestration/src/routing.py::parse_catalog_entries`/`load_catalog`, `agents/orchestration/src/generate_role_metadata.py::ALLOWED_PHASES`/`TIER_MAP`/`_validate_record`, `agents/orchestration/src/generate_global_plugin.py::ALLOWED_MODELS`/`ALLOWED_CODEX_MODELS`/`ALLOWED_REASONING_EFFORTS`/`CAPABILITY_PROFILES`, `agents/orchestration/test/test_repository_health.py::test_catalog_declares_capabilities_and_reviewers_are_read_only`.

- **SV-FR-1:** For every top-level entry under `catalog.yaml`'s `agents:` map, the validator confirms all six documented fields are present and non-empty: `definition`, `phase`, `capability`, `model`, `codex_model`, `reasoning_effort`. A missing or empty field is a finding naming the role id and the missing field.
- **SV-FR-2:** `definition` must resolve, relative to `agents/`, to a file that exists on disk (sourced from `test_catalog_definitions_and_agent_files_stay_in_sync`'s existing check, restated here as a standalone-validator obligation rather than only a repository-health test).
- **SV-FR-3:** `phase` must be one of the 13-value closed set already defined in `generate_role_metadata.py::ALLOWED_PHASES` (`planning`, `design`, `security`, `build`, `verify`, `review`, `release`, `operations`, `support`, `document`, `evidence`, `knowledge`, `authority`). Any other value is a finding naming the role id, the offending value, and the allowed set.
- **SV-FR-4:** `capability` must be one of the 5-value closed set already enforced by `generate_global_plugin.py::CAPABILITY_PROFILES` / restated in `test_repository_health.py` (`read_only`, `document_author`, `code_author`, `test_author`, `environment_operator`).
- **SV-FR-5:** `model`, `codex_model`, and `reasoning_effort` must together match one row of the existing 3-row `TIER_MAP` (`opus`/`gpt-5.6-sol`/`high`, `sonnet`/`gpt-5.6-terra`/`medium`, `haiku`/`gpt-5.6-luna`/`low`); a mismatched combination (e.g. `model: opus` with `reasoning_effort: medium`) is a finding naming the role id and the specific inconsistent field(s), not just "invalid tier."
- **SV-FR-6:** Every role id under `agents:` is unique (already enforced structurally by `parse_keyed_entries` raising on first duplicate; this requirement asks the standalone validator to report **all** duplicates found in one pass rather than stopping at the first, since `parse_keyed_entries`'s fail-fast behavior is a parsing concern, not a validation-completeness concern — see Gap G-2).

**Explicit non-goal restated from intent §5:** this group does not re-derive or cross-check `catalog.yaml` against `AGENT.md` frontmatter (that is `generate_role_metadata.py --check`'s existing job, unmodified); it validates `catalog.yaml`'s own shape in isolation, as a project consuming only that file would need to.

## 4. Functional requirements — routing.yaml (full documented shape)

Grounding: `agents/orchestration/routing.yaml` (read 2026-07-29, JSON syntax despite the `.yaml` filename — confirmed by `routing.py::load_routing`'s `json.load`), `agents/orchestration/src/routing.py::load_routing`/`match_rule`, `agents/orchestration/src/build_dispatch_plan.py` (consumer of `ignored_gates`, `human_gate`, `communication_mode`, `quality_gates`), `agents/orchestration/src/routing_health.py::_iter_references` (existing reference-location convention reused here).

**Top level:**
- **SV-FR-7:** `version` must be the integer `1` (already checked by `load_routing`; restated as a standalone-validator obligation so the new validator does not depend on `load_routing` raising first and stopping all other checks — see SV-NFR-2).
- **SV-FR-8:** `ignored_gates`, if present, must be a list of strings. **This field is not named in the intent record's §4 Scope enumeration** — flagged as new Gap G-3 (§8) rather than silently added or silently dropped from scope.

**`change_intake` (object):**
- **SV-FR-9:** `keywords` must be a non-empty list of non-empty strings.
- **SV-FR-10:** `agents` must be a non-empty list of strings (cross-referenced against `catalog.yaml` agent ids is `routing_health.py`'s job per idea #1, not re-validated here — shape/type only).
- **SV-FR-11:** `quality_gates`, if present, must be a list of strings matching the `G\d+` lifecycle-gate id shape.

**`routes[]` (list of objects) and `risk_rules[]` (list of objects) — shared shape:**
- **SV-FR-12:** Every entry has a unique, non-empty string `id` (uniqueness already enforced by `load_routing` across routes+risk_rules+team_recipes combined; restated per-array for finding precision).
- **SV-FR-13:** `paths`, if present, must be a list of strings (glob patterns; the validator does not need to compile/execute them — that is `routing.py::glob_to_regex`'s existing job at match time).
- **SV-FR-14:** `keywords`, if present, must be a list of non-empty strings.
- **SV-FR-15:** `keyword_groups`, if present, must be a list of non-empty lists of non-empty strings (already enforced by `load_routing`; restated for standalone-validator parity with per-field location reporting rather than a single generic `ValueError`).
- **SV-FR-16:** `primary`, `reviewers`, `support`, if present, must each be a list of strings (cross-reference against `catalog.yaml` — idea #1's job, not re-validated here).
- **SV-FR-17:** `quality_gates`, if present, must be a list of strings matching the `G\d+` shape.
- **SV-FR-18 (risk_rules only):** `human_gate`, if present, must be a non-empty string. (Whether every `human_gate` value has a corresponding description elsewhere — the "remaining 17" backlog list's item 14 — is a distinct completeness check against a second artifact outside this baseline's two named files; **left as a candidate follow-on, not claimed here** — see Gap G-4.)

**`cross_stack` (object):**
- **SV-FR-19:** `route_ids` must be a non-empty list of strings; each value's *existence* as a real `routes[].id` is a reachability concern already covered by `routing_health.py`'s reference iteration and is explicitly not duplicated here — this requirement covers type/shape only (list-of-strings), matching the type/shape-vs-reachability split the intent record itself draws in §5.
- **SV-FR-20:** `minimum_matches` must be a positive integer, and (new observation, not in today's `load_routing`) should not exceed `len(route_ids)` — a `minimum_matches` value unreachable by the declared `route_ids` set would be a live latent-defect class this validator is well positioned to catch since it is a pure shape/consistency check, not a reachability check. Flagged as a **candidate net-new check beyond the intent record's explicit list** (see Gap G-5) rather than silently added.
- **SV-FR-21:** `support`, if present, must be a list of strings.

**`team_recipes[]` (list of objects):**
- **SV-FR-22:** Every entry has a unique, non-empty string `id`, a `type` of exactly `"fixed"` or `"dynamic"` (the only two values present in current `routing.yaml` and the only two branches `build_dispatch_plan.py` implements), a `communication_mode` of exactly `"peer"` or `"orchestrator-relayed"` (the only two values in current `routing.yaml`, matching `.agents/skills/run-agent-orchestration/references/runner-adapters.md`'s documented contract), and (if `communication_mode` is `"peer"`) a `fallback` field, and a non-empty `description` string.
  - **`type: "fixed"` variant:** `route_ids` (non-empty list of strings), `minimum_matches` (positive integer, same `<= len(route_ids)` consistency check as SV-FR-20), `members` (non-empty list of strings), `minimum_members_selected` (positive integer, and — new observation — should not exceed `len(members)`; same Gap G-5 class).
  - **`type: "dynamic"` variant:** `role` (non-empty string), `instances` (object with integer `min`/`max`, `1 <= min <= max`, already enforced by `load_routing`; restated for per-field location precision), `requires_route` (non-empty string; existence as a real `routes[].id` is idea #1's reachability job, not re-validated here), `keywords` (non-empty list of non-empty strings).
- **SV-FR-23:** A `team_recipes[]` entry must not mix `type: "fixed"`-only fields (`route_ids`/`minimum_matches`/`members`/`minimum_members_selected`) with `type: "dynamic"`-only fields (`role`/`instances`/`requires_route`) — cross-contamination is a finding naming the recipe id and the out-of-type field(s) present.

**`knowledge_focus` (object):**
- **SV-FR-24:** Every key must be a non-empty string and every value must be a non-empty string (the map's *completeness* against every routed catalog agent — the "remaining 17" list's item 1 — is a distinct cross-file completeness check, not this baseline's shape/type validation; **not claimed here**, see Gap G-4).

## 5. Functional requirements — reporting, boundary, and interface behavior

- **SV-FR-25 (location precision, per intent C-5/SC-1):** Every finding names the exact field and, where the field is inside a list, the index and (where the containing object carries an `id`) the id — matching `routing_health.py::_iter_references`'s existing `routes[6] (id="orchestration").reviewers[0]`-style location string convention and `test_repository_health.py`'s precise-mismatch reporting style. A finding that only says "routing.yaml is invalid" without a field/index/id does not satisfy this requirement.
- **SV-FR-26 (exhaustive-per-run reporting):** A single validator run against a file with multiple independent defects reports all of them in one pass rather than stopping at the first (a defect-completeness property distinct from SV-FR-25's per-finding precision) — necessary for SC-1's "detected... demonstrable via a negative fixture" to remain true when a fixture intentionally carries more than one defect for test economy.
- **SV-FR-27 (additive boundary, per intent C-6/SC-4, testable definition):** "Additive to idea #1 and `test_repository_health.py`, not a replacement" is operationalized as: (a) the new validator ships as a new file or files, not an edit to `routing_health.py` or `test_repository_health.py`'s existing test bodies; (b) `routing_health.py::run`/`check_routing_coverage` and every existing `test_repository_health.py` test method's assertions are byte-for-byte unmodified by this work; (c) the new validator's own tests are wired into the existing `unittest discover -s agents/orchestration/test -p "test_*.py"` invocation as one or more additional test files, not a new discovery root or invocation the operator must separately remember.
- **SV-FR-28 (CLI convention, per intent §4 bullet 3 "runnable standalone"):** The validator is invocable as a standalone script following the existing `--check`-flag convention shared by `generate_authority_aides.py`, `generate_role_metadata.py`, and `generate_global_plugin.py` — i.e. it exits non-zero with findings on stderr when invalid, and exits zero (optionally printing a summary) when clean, without requiring any other generator to run first. Whether it is literally a new sibling script (matching idea A/B's "new sibling module" precedent) versus a function imported directly by a `test_*.py` module (matching idea A/B's own ship-as pattern, where the CLI-style `main()` coexists with a thin test wrapper) is an implementation-approach question folded into OD-2, not resolved here.

## 6. Non-functional requirements

- **SV-NFR-1 (standalone runnability, C-1):** The validator must run to completion under `python3 -m unittest discover -s agents/orchestration/test -p "test_*.py"` with no other generator invoked first and no environment variable (e.g. `AGENTIC_SDLC_BIN`) required for its core catalog/routing shape checks. (SV-FR-11/SV-FR-17's `G\d+`-shape check is a string-pattern check only and does not require the kernel; a *semantic* "is `G7` a real gate" check would require the kernel and is out of this baseline's scope — see Gap G-4's cross-reference to the "remaining 17" list's item 3.)
- **SV-NFR-2 (fail-closed, deterministic):** Given the same file content, the validator produces the same ordered finding list on every run; a structurally-invalid file (e.g. malformed JSON) is itself a reportable failure (with the parse error surfaced, not swallowed), not a silent pass. The validator must not depend on `load_routing()` or `load_catalog()` raising and halting before other independent checks run — see SV-FR-7's rationale.
- **SV-NFR-3 (simplicity/no dependency creep, C-2/C-4, intent OD-2 boundary respected):** Given `catalog.yaml` and `routing.yaml` are both small (47 role blocks; ~30 routing structures as of 2026-07-29) hand-authored files, the validator must not require adding general-purpose YAML/JSON-Schema parsing capability to `routing.py`'s existing loaders as a side effect (per C-2). This baseline does not mandate an implementation approach (C-4) but records, for the requirements/design phase's OD-2 resolution, that: (a) a hand-written validator function following `generate_role_metadata.py::_validate_record`'s existing pattern needs **zero new dependencies** and is the lowest-risk default under `library-standards.yaml`'s "prefer standard library when sufficient" rule; (b) `PyYAML==6.0.3` is already an approved, pinned, justified dependency elsewhere in this repository (`agents/shared/requirements-validation.txt`, used by `agents/shared/src/resolve.py`) and is available as precedent if the design phase later needs real YAML parsing for some other reason, but `catalog.yaml`/`routing.yaml` are deliberately parsed today by hand-rolled parsers rather than PyYAML/`json`, and this baseline does not propose changing that; (c) a JSON-Schema-based approach (extending the `agents/orchestration/selection.schema.json` precedent — `routing.yaml` is already JSON syntax, so this is mechanically plausible) would still need either a new `jsonschema`-family dependency (requiring `library-standards.yaml`'s new-dependency justification, pinned version, license/vulnerability review — none of which is performed here) or a hand-rolled JSON Schema interpreter (functionally equivalent to (a) with added indirection). No concrete reason was found during this decomposition to prefer (c) over (a); this is recorded as a recommendation for the design phase to confirm or override, not a decision this record is authorized to make (C-4).
- **SV-NFR-4 (non-weakening, C-6):** Adding this validator must not require modifying `routing_health.py`'s existing functions/assertions or any existing `test_repository_health.py` test method to keep passing.
- **SV-NFR-5 (performance):** Given file sizes as of 2026-07-29 (47 catalog roles, ~30 routing.yaml routes/risk_rules/team_recipes combined), no numeric runtime budget is set here (per intent §10, numeric targets are a requirements/design, not intent, decision — and this requirements pass likewise declines to invent one absent an approved SLA) beyond the qualitative expectation, sourced from Item A/B's precedent (<1s / "low seconds"), that a validator over files this size should not become a noticeable addition to the existing `unittest discover` run.
- **SV-NFR-6 (no overlay-compatibility assumption, intent §5):** The validator is built and tested against this repository's own `catalog.yaml`/`routing.yaml` only; it must not assume compatibility with idea #6's not-yet-designed project-local routing-overlay semantics.

## 7. Dependencies, assumptions, applicability

**Dependencies:**
- Sequenced after idea #3 per the backlog table and intent A-2 — confirmed genuinely satisfied: `generate_role_metadata.py` (item #3's generator) is present, functioning, and already wired into `test_repository_health.py` as of this decomposition (2026-07-29), so this baseline's `catalog.yaml`-facing requirements (§3) are being written against item #3's *actual* post-migration shape, not a hypothetical one. No residual blocking dependency on item #3 remains.
- Complementary, non-blocking relationship to idea #1 (`routing_health.py`, shipped) — this baseline's requirements are additive per SV-FR-27/SV-NFR-4 and do not require idea #1 to change.
- No dependency on idea #6 (project-local routing overlay) — idea #6 is sequenced *after* #10 per the backlog table and is explicitly not assumed compatible (SV-NFR-6).
- `SV-FR-11`/`SV-FR-17`'s optional deeper semantic gate-id check (noted but not required by SV-NFR-1) would depend on `AGENTIC_SDLC_BIN`/the standalone `agentic-sdlc` executable, matching the existing `_require_agentic_sdlc()` skip-when-absent pattern already used elsewhere in `test_repository_health.py` — not a hard dependency for this baseline's in-scope shape checks.

**Assumptions (labeled, not asserted as approved fact):**
- **AS-1:** `catalog.yaml`'s current fully-generated status and `routing.yaml`'s partially-generated (`knowledge_focus`-only) status, as observed 2026-07-29, are stable enough to decompose requirements against; a future further migration of `routing.yaml`'s other blocks into generated output would require revising §3/§4's split, not silently invalidate it.
- **AS-2 (inherited from intent A-3):** "Strict" continues to be read as "complete/authoritative for the documented shape," not as a specific enforcement mechanism — OD-4 remains open (§8).
- **AS-3:** The `G\d+` lifecycle-gate id shape check (SV-FR-11/SV-FR-17) validates *string shape* only; it is not a claim that the referenced gate is a real, currently-defined `agentic-sdlc` gate — that would be Gap G-4's deferred semantic check.

**Gate/lifecycle applicability (this repository has no `.agentic-sdlc/` overlay of its own; recorded per role-required convention for downstream project consumption):**

| Gate | Applicability | Note |
|---|---|---|
| G1 Intent | applicable | Intent record already produced; awaiting human Product Owner approval (OD-1 blocks this) |
| G2 Requirements Baseline | applicable | This document |
| G3 Architecture | applicable | Implementation-approach decision (OD-2) belongs here |
| G4 Governance/Data | not-applicable | No governance/data-classification surface touched (repo-tooling change, no runtime/production data) |
| G5 Security | unknown | No security-relevant surface identified (read-only static validation of internal config files), but not affirmatively ruled out by this record — flagged rather than assumed, per this role's "unknown material applicability blocks the baseline" rule; **non-blocking** because the underlying activity (adding a read-only static text validator) does not itself meet any `routing.yaml` risk_rule trigger keyword/path (checked against `authentication-authorization`, `sensitive-data`, `public-exposure`, `identity-privilege` — no match) |
| G6 Test/Verification | applicable | Negative-fixture and clean-baseline tests (AC-1..AC-8) |
| G7 Evidence | applicable | Test-suite pass output is the evidence artifact; no separate evidence-curator involvement identified as needed |
| G8/G9 Release/Deploy | not-applicable | No deployable artifact beyond the existing repository-tooling test suite; no production/persistent-environment mutation (intent §7) |
| G10 Runtime | not-applicable | No runtime/production surface |

## 8. Conflict and gap register

No conflicts were found between this decomposition and the intent record. Gaps and requirements-level open questions discovered during decomposition:

| ID | Description | Status | Disposition |
|---|---|---|---|
| G-1 | Intent §3/Users-beneficiaries framed `catalog.yaml` as hand-edited like `routing.yaml`; current code shows it is fully generated by `generate_role_metadata.py`, with existing fail-closed per-role validation already wired into `test_repository_health.py`. This materially narrows (but does not eliminate — see §0's "Consequence for scope") the net-new work needed for `catalog.yaml`. | Resolved in this decomposition | See §0; §3's requirements are scoped to a frontmatter-independent standalone re-validation, justified by the intent's own "external consuming projects" beneficiary. |
| G-2 | `parse_keyed_entries`'s duplicate-id check is fail-fast (raises on first duplicate) rather than exhaustive; a standalone validator promising "report all findings in one pass" (SV-FR-26) needs its own duplicate-detection pass rather than delegating to `load_catalog`/`load_routing` for that specific check. | Open, non-blocking | Implementation-approach question (part of OD-2 scope), not a requirements gap — flagged so the design phase does not silently assume `load_catalog`/`load_routing` alone satisfy SV-FR-26. |
| G-3 | `routing.yaml`'s top-level `ignored_gates` field is not named anywhere in the intent record's §4 Scope enumeration, but is real, current-schema, and consumed by `build_dispatch_plan.py`. | Resolved in this decomposition | Added as SV-FR-8, in scope. |
| G-4 | Several adjacent completeness/semantic checks were surfaced while enumerating routing.yaml's shape but are explicitly out of this baseline's shape/type-validation scope: (a) `human_gate` description-completeness against wherever gate descriptions live outside these two files ("remaining 17" list item 14); (b) `knowledge_focus` completeness against every *routed* catalog agent, a cross-file reachability concern closer to idea #1's family than to shape validation ("remaining 17" list item 1); (c) semantic validity of `quality_gates`/`human_gate`-adjacent `G\d+` ids against the live `agentic-sdlc` gate list, not just string shape ("remaining 17" list item 3). | Open, non-blocking | Recorded as candidate follow-on backlog scope, not silently folded into or silently excluded from idea #10 — requires an explicit accountable-owner decision on whether they belong in this build or a separate backlog item, since (a)/(b) require reading data outside `catalog.yaml`/`routing.yaml`. |
| G-5 | `cross_stack.minimum_matches <= len(route_ids)` and `team_recipes[].minimum_members_selected <= len(members)`/`minimum_matches <= len(route_ids)` internal-consistency checks are a natural extension of shape validation (both fields are read together by `build_dispatch_plan.py`) but were not explicitly enumerated in the intent record. | Resolved in this decomposition | Added as SV-FR-20 (and cross-referenced from the `team_recipes` fixed-variant bullet under SV-FR-22); flagged rather than silently added, since it is a defect class not literally listed in intent §4. |
| OD-1 (carried forward) | Accountable Product Owner for this repository's backlog is still unnamed. | **Blocking G1** | Unchanged from intent record; this requirements baseline cannot itself resolve it. |
| OD-2 (carried forward) | Implementation approach (hand-written validator vs. JSON Schema vs. typed-model library vs. extending `routing.py`). | Open, non-blocking for this baseline | Narrowed by SV-NFR-3's analysis (no concrete reason found to prefer a new dependency); final selection remains a design-phase/code-review decision, not made here. |
| OD-3 (carried forward, requested "do the enumeration now") | Full enumeration of structural gaps in existing code vs. intent §3's list. | **Resolved in this decomposition** | §4's per-field requirement list (SV-FR-7..SV-FR-24) is the requested exhaustive enumeration, cross-checked directly against `routing.yaml`'s current on-disk content and `routing.py`/`build_dispatch_plan.py`'s consuming code, not against intent §3's list alone. G-3/G-4/G-5 above record what the enumeration additionally surfaced. |
| OD-4 (carried forward) | Enforcement mode (fail-closed CI gate vs. advisory vs. staged). | Open, non-blocking | Unchanged; SV-FR-28 deliberately specifies only the CLI *interface* contract (exit codes/`--check`), not whether CI treats a non-zero exit as blocking. |
| OD-5 (carried forward) | Whether `agents/orchestration/selection.schema.json` (dispatch-plan *output* schema) is in scope. | **Resolved in this decomposition, confirming intent's reading** | Out of scope. §3/§4 validate only `catalog.yaml` and `routing.yaml` (the backlog title's named *input* files); `selection.schema.json` already has its own consumer (`test_repository_health.py::test_workflow_values_match_schema_and_files`) and is a plan-output contract, a different artifact class from the two hand/generator-authored config files this baseline targets. |

## 9. Acceptance criteria

Matching Item A/B's acceptance-criteria format and depth:

- **AC-1 (clean baseline, SC-2):** Run against the current, unmodified `agents/catalog.yaml` and `agents/orchestration/routing.yaml` → zero findings.
- **AC-2 (catalog negative fixture, SC-1):** A fixture copy of `catalog.yaml` with one role's `phase` set to an unrecognized value → the validator names that exact role id, the field (`phase`), the offending value, and the allowed set (SV-FR-3, SV-FR-25).
- **AC-3 (catalog tier-mismatch fixture):** A fixture copy of `catalog.yaml` with `model: opus` paired with `reasoning_effort: medium` (a real cross-field inconsistency class, not just a bad enum value) → the validator names the role id and the specific mismatched field(s) (SV-FR-5).
- **AC-4 (routing type-shape fixture):** A fixture copy of `routing.yaml` with a route's `reviewers` field set to a string instead of a list → the validator names the route id, field, and index/location using `routing_health.py`-style location strings (SV-FR-16, SV-FR-25).
- **AC-5 (team_recipe cross-contamination fixture):** A fixture `team_recipes[]` entry with `type: "fixed"` that also carries a `dynamic`-only field (e.g. `requires_route`) → the validator names the recipe id and the out-of-type field (SV-FR-23).
- **AC-6 (multi-defect single pass, SV-FR-26):** A fixture carrying two independent, unrelated defects (e.g. one in `catalog.yaml`, one in `routing.yaml`, or two in `routing.yaml`) → a single validator run reports both findings, not just the first.
- **AC-7 (additive-boundary demonstration, SC-4, SV-FR-27):** After the new validator ships, `routing_health.py`'s existing functions and every pre-existing `test_repository_health.py` test method are byte-for-byte unchanged (diff-verifiable), and all of them still pass in the same `unittest discover` run as the new validator's own tests.
- **AC-8 (standalone runnability, SC-3, SV-NFR-1):** The validator's core catalog/routing shape checks (excluding any optional kernel-dependent semantic gate-id check) run to a pass/fail result without invoking `build_dispatch_plan.py`, `generate_global_plugin.py`, or `generate_role_metadata.py`, and without `AGENTIC_SDLC_BIN`/`agentic-sdlc` on `PATH`.

## 10. Ship-as / sequencing note

- **Confirmed unblocked:** idea #3 (agent-authoring restructuring) has shipped and its generator (`generate_role_metadata.py`) is present, functioning, and already exercised by `test_repository_health.py` as of 2026-07-29 — the backlog's "sequence after #3" dependency is satisfied, matching intent A-1/A-2.
- **No residual dependency on idea #1:** `routing_health.py` is complete and independently testable; this baseline's validator is additive per SV-FR-27/SV-NFR-4 and does not need idea #1 to change first, though (per SV-FR-16/SV-FR-19's explicit type-vs-reachability split) the two remain deliberately complementary rather than merged.
- **Residual dependency worth flagging for the build phase (not a blocker):** Gap G-1's finding that `catalog.yaml` is now generated output changes the natural "ship as" shape — a new sibling module (matching Item A/B's precedent of new files, not edits to `test_repository_health.py` or `routing_health.py`) remains correct, but the build phase should confirm whether the `catalog.yaml`-facing checks (§3) are worth shipping as a wholly separate concern from the `routing.yaml`-facing checks (§4), since §3's marginal value is now narrower (Gap G-1) than §4's. This requirements baseline does not resolve that split — it is folded into OD-2's implementation-approach decision.
- **Recommended relative position:** build after idea #1/#2 are merged/verified (already the case per the prior requirements pass's disposition) and after this record's OD-1 (accountable Product Owner) is resolved enough to clear G1 for the parent intent record — no other lifecycle blocker was found.

---

## Handoff

This baseline is ready for G2 Requirements Baseline Gate review. It does not resolve OD-1 (blocking G1 on the parent intent), OD-2, OD-4, or the newly-surfaced G-2/G-4 items, all of which remain open and are carried into the design/build phase rather than silently assumed. OD-3 and OD-5 are resolved by this decomposition (§8). Every requirement in §3-§6 traces to either current on-disk file content, existing code (`routing.py`, `generate_role_metadata.py`, `generate_global_plugin.py`, `build_dispatch_plan.py`, `routing_health.py`, `test_repository_health.py`), or is explicitly flagged as a net-new observation (G-3, G-5) rather than silently presented as pre-existing scope.
