# Product Intent Record — Provenance binding in dispatch plan

**Intent ID:** `INTENT-CADRE-BACKLOG-7`
**Revision:** 1 (initial)
**Status:** draft — awaiting human Product Owner review at G1
**Author (agent):** product-intent-agent
**Date:** 2026-07-29
**Repository:** `/home/deagy/sdk/cadre`
**Classification:** internal
**Source backlog item:** `agents/orchestration/runs/cadre-feature-backlog-requirements-2026-07-28/requirements.md`, priority table row #7 ("Provenance binding in dispatch plan" — P1 — Beneficiary: Auditors/reviewers — Dependency: pairs with #8, declarative runner capability manifest). Priority (P1) was set by the prior product-intent-agent framing pass on 2026-07-28 and is carried forward here as approved context, not re-decided by this record — see "Explicitly not decided here."

---

## 0. Correction to dispatch framing (read before the rest of this record)

The dispatch instruction for this record described idea #8 (declarative runner capability manifest) as "now shipped" and suggested checking `agents/runner-capabilities.json` and `agents/orchestration/src/routing_overlay.py`. Grounding against the actual repository state on 2026-07-29 found neither exists:

- `find /home/deagy/sdk/cadre -iname "*runner-capabilit*"` — no results.
- `find /home/deagy/sdk/cadre -iname "*routing_overlay*"` — no results (only unrelated git branch-name matches for `remove-repository-lifecycle-overlay` and `fix/autonomy-overlay-narrowing-bypass`, which are not this idea).
- `git log --oneline -10` shows the most recent shipped backlog work is idea #10 (strict catalog/routing schema validation, `a566ebc`) and a pip/pipx packaging change — idea #8 and idea #6 (project-local routing overlay) are not among them.

This record therefore treats idea #8 and idea #6 as **not yet built**, contrary to the dispatch instruction's framing, and logs this as OD-1 in the open-decision register rather than silently assuming either exists. This does not block writing this intent record (per this role's requirement to structure and clarify intent even where an upstream dependency is still open), but it materially changes the dependency picture: idea #7 pairs with idea #8, and idea #8 has not shipped, so the manifest-hash portion of "provenance" described below is a description of a problem against artifacts that do not yet exist on disk. Idea #10 (schema validation) *has* shipped and is grounded directly below.

## 1. Owner

**Accountable Product Owner:** not named in any source document read for this record, for the same reason recorded in the sibling idea #10 intent record (`agents/orchestration/runs/cadre-idea-10-schema-validation-2026-07-29/product-intent.md`, OD-1): `team-profile.yaml`'s `out_of_scope_standards` block names Daniel Eagy as Product Owner for a specific, unrelated compliance-scope decision (2026-07-26) only. Nothing in the backlog, `AGENTS.md`, `CLAUDE.md`, or `RUNBOOK.md` designates a Product Owner role for this repository's own feature backlog. Logged as OD-2 in the decision register rather than assumed.

**Working owner for this intent record's authorship:** product-intent-agent (this agent), acting on the orchestrator's dispatch instruction that named idea #7. Authorship does not confer approval authority.

## 2. Users / beneficiaries

Restating the backlog's own beneficiary line, traced to concrete roles and artifacts rather than left generic:

- **Auditors and reviewers examining a historical dispatch plan or run-evidence artifact after the fact** — the backlog's named primary beneficiary. Concretely, this includes: the `security-reviewer`, `pipeline-security-reviewer`, and `compliance-reviewer`-class roles named in `agents/orchestration/routing.yaml`'s review-cluster routes; the human Product Owner or approval group reviewing a G1–G10 lifecycle gate record in a project that has adopted the `agentic-sdlc` kernel with Cadre's `secure-cloud` profile; and any future incident investigation or governance review that needs to answer "what suite configuration actually produced the agent selection and gate set recorded for this specific historical task."
- **Suite maintainers** who need to reproduce or explain a past `cadre select` result when catalog/routing/runner-capability content has since changed, and who currently have no artifact-level way to prove a given plan came from a specific prior suite state.
- **Consuming projects** that archive `cadre select` output as part of their own run evidence (see `agents/orchestration/runs/` for this repository's own precedent of archiving dispatch-adjacent artifacts per task) and need that archived plan to remain independently verifiable later, not merely trusted at time of generation.

## 3. Problem statement (WHAT and WHY)

A dispatch plan produced by `build_dispatch_plan()` (`agents/orchestration/src/build_dispatch_plan.py`) already carries a `dispatch_fingerprint` field (`selection.schema.json` requires it: `^sha256:[0-9a-f]{64}$`). Grounding exactly what that field does and does not capture, read directly from the implementation:

**What `dispatch_fingerprint` actually computes today:** it is `sha256` of the canonical JSON serialization (`sort_keys=True`, compact separators) of the *plan's own output dictionary*, with only `generated_at` and `dispatch_fingerprint` itself excluded (`build_dispatch_plan.py`, final ~10 lines). In other words, it is a self-consistency checksum over the plan's own emitted content — `schema_version`, `task_id`, `status`, `workflow`, `inputs`, `matched_routes`, `matched_risks`, `agents`, `teams`, `lifecycle_tracking`, `required_quality_gates`, `ignored_quality_gates`, `gate_dispatch`, `human_gates`, `knowledge_context`. Backlog item #10 in `requirements.md`'s "Remaining 17" list independently names its intended purpose: "Dispatch-fingerprint stability — same inputs → same fingerprint across runs" — i.e. a determinism/reproducibility check for a single run, not a provenance binding across time.

**What it does NOT capture (the gap this idea addresses):** the fingerprint does not reference, hash, version-pin, or otherwise bind the plan to any identifier for:
- the exact content of `agents/catalog.yaml` that was loaded to build the `catalog` list passed into `build_dispatch_plan()` (read by `build_dispatch_plan.py`'s caller, not by this function itself, and not represented in its output at all);
- the exact content of `agents/orchestration/routing.yaml` that was loaded as `config` (same — consumed as an argument, never echoed or hashed into the output);
- whether a project-local routing overlay was in effect and, if so, its content (idea #6 — not yet built per Section 0, but the underlying question — "was the effective routing config the base suite's routing.yaml, or a base-plus-overlay merge, and what did the overlay contain" — is a real provenance gap regardless of when #6 ships, because once it does ship, an overlay-modified plan would be indistinguishable from a base-only plan by fingerprint alone unless this gap is closed);
- the runner-capability manifest content (idea #8 — not yet built per Section 0) that would determine which runner-specific behavior (e.g. `communication_mode`/`fallback` team semantics) applied at generation time;
- a repository/commit identifier (e.g. git SHA) tying the plan to a specific point in this repository's own history;
- the version of `agentic_sdlc_contracts`'s lifecycle contract (`gates` list) when `lifecycle_tracking.status == "integrated"` — the gate `id`/`name`/`phase`/`author_agents`/`review_agents` content contributing to `required_quality_gates` and `gate_dispatch` comes from an external `agentic-sdlc` executable resolved at runtime, and only the *resulting* gate list is embedded in plan output, not an identifier for which version of that external kernel produced it.

**Consequence:** an auditor holding a historical dispatch plan JSON artifact today can confirm the plan is internally self-consistent (the fingerprint matches its own content) and, per idea #10's stated intent, that re-running with the *same catalog/routing files* would reproduce the same plan — but cannot verify, from the artifact alone, *which* catalog.yaml, routing.yaml, (future) overlay, (future) runner-capabilities manifest, or external lifecycle-contract version actually produced it, nor detect that any of those inputs have since changed. If `catalog.yaml` or `routing.yaml` is edited after a plan was generated and archived, nothing in the archived plan lets a reviewer later distinguish "this plan reflects the suite state as it existed on the date recorded in `generated_at`" from "this plan's stated routes/agents/gates no longer correspond to any actual current or past routing.yaml content that can be located and checked." `generated_at` records *when* the plan was produced, not *from what*.

**Desired outcome:** a human or automated auditor, given an archived dispatch plan artifact and access to this repository's history (or a project's copy of the suite), can verify — without re-trusting the process that produced the plan — exactly which versions/content of the suite inputs (at minimum: catalog, routing config, and, once they exist, any project-local overlay and the runner-capability manifest) were in effect when that specific plan was generated. This closes a specific, named gap in today's `dispatch_fingerprint` (a self-consistency check, not a suite-state binding) rather than replacing it.

## 4. Scope

In scope for this intent (the *problem space* this backlog item addresses — not an implementation mandate):

- Recording, in the dispatch plan artifact itself, sufficient identifying information about the exact content/version of `agents/catalog.yaml` and `agents/orchestration/routing.yaml` that were loaded to produce that plan, such that a later reviewer can verify — not merely trust — that a specific historical copy of those files is the one that produced a specific historical plan.
- Extending that same binding to cover a project-local routing overlay (idea #6) and a runner-capability manifest (idea #8), once either exists, so that "provenance" is not left with a gap the moment those companion features ship. This intent does not build #6 or #8, and does not assume a specific shape for either — see Exclusions and OD-1.
- Making the binding auditable independent of trusting the generating process — i.e., the artifact itself (or the artifact plus something independently reproducible, such as this repository's own git history) must be sufficient for verification, not merely a claim embedded by the same code that could also be the source of an error.
- Clarifying the relationship between this new binding and the existing `dispatch_fingerprint` field: whether provenance binding extends `dispatch_fingerprint`'s coverage, adds sibling field(s) alongside it, or both — left to the requirements/design phase (see Exclusions), but the *problem* of "the existing field is a self-consistency check, not a suite-state binding" is the scope this intent defines.

## 5. Exclusions (explicitly out of scope for this intent)

- **Implementation approach is not decided here.** Whether provenance is recorded as a git commit SHA, a content hash of each input file, a signed attestation, a reference to an external ledger/evidence store, or some combination, is a requirements/design decision, not a product-intent decision, per this role's authority limits. See OD-3.
- **Whether the binding is cryptographically verifiable (e.g. signed) versus merely recorded/inspectable is not decided here.** The backlog beneficiary is "auditors/reviewers," which implies verifiability matters, but the strength of that guarantee (plain hash vs. signed attestation vs. externally-anchored evidence) is a design tradeoff this record does not resolve. See OD-4.
- **This intent does not build idea #8 (runner-capability manifest) or idea #6 (routing overlay).** Both are named dependencies/companions per the original backlog framing, and Section 0 above corrects the dispatch instruction's assumption that #8 already shipped — neither exists in this repository as of 2026-07-29. This intent describes the provenance-binding problem in a way that anticipates both existing, without assuming their eventual shape.
- **No decision on whether provenance binding is mandatory (schema-required, like today's `dispatch_fingerprint`) or optional/advisory.** `selection.schema.json` currently requires `dispatch_fingerprint` in every plan; whether a new provenance field gets the same treatment is a scope/priority decision for requirements or design. See OD-5.
- **No decision on external lifecycle-contract (`agentic-sdlc` kernel) version binding scope.** Section 3 names this as a related gap (the gate list embedded in a plan doesn't identify which kernel version produced it), but whether closing that gap is in scope for this backlog item specifically, or is a separate future backlog item, is left open. See OD-6.
- **No performance, storage-growth, or backward-compatibility commitments** for existing consumers of `selection.schema.json`-shaped plans (e.g. golden-corpus fixtures from item B, which the requirements baseline already documents as normalizing/excluding `dispatch_fingerprint` from comparison — a new provenance field would need the same treatment, but deciding that is downstream design/requirements work, not intent).

## 6. Constraints

Traced to existing approved repository policy and code, not invented:

- **C-1 (this role's authority limit):** this record may not mandate a specific hashing scheme, commit-SHA binding, or signing mechanism; it may only state the problem, desired outcome, and flag the tradeoff as open (mirrors idea #10's C-4).
- **C-2 (`agents/shared/operating-principles.md`):** "base claims on inspectable evidence" — any eventual provenance mechanism must itself be inspectable/independently checkable by the stated beneficiary (auditors/reviewers), not merely a self-reported claim from the same process being audited. This is the substantive requirement driving Section 3's "without re-trusting the process that produced the plan" framing, and is a constraint this record is authorized to state even though it cannot pick the mechanism.
- **C-3 (`AGENTS.md`/`CLAUDE.md`/`RUNBOOK.md` convention, mirrored from idea #10 C-1):** whatever emerges from this intent should remain runnable/verifiable under this repository's existing lightweight tooling conventions (`python3 -m unittest discover`, standalone CLI invocation) rather than introducing a dependency on infrastructure this repository does not otherwise operate (e.g. a production ledger service) unless a future design phase explicitly justifies one.
- **C-4 (repo boundary, `CLAUDE.md`/`AGENTS.md`):** this repository does not own lifecycle gate schemas, run-record validation, or gate-authority semantics — those belong permanently to `deagy/agentic-sdlc`. Any provenance mechanism touching `lifecycle_tracking`/`required_quality_gates`/`gate_dispatch` content sourced from the external kernel must not have Cadre infer or assert gate approval or authority; it may only record which kernel version/content contributed inputs, consistent with `cadre select`'s existing role as "emits a plan only."
- **C-5 (`library-standards.yaml`):** any new dependency (e.g. a signing library) needs documented technical rationale, pinned version, license review, and vulnerability/supply-chain review before adoption — not assumed in scope for this intent record.
- **C-6 (`agents/shared/operating-principles.md`, "do not silently weaken... approval gates"):** provenance binding must not become a substitute for, or dilution of, existing human-approval gates (`agent-autonomy.yaml`'s `governance` block: `approve_own_work: never`, `accept_security_or_compliance_risk: never`). Proving *what produced* a plan is not the same as, and must not be conflated with, *approving* that plan.

## 7. Environments

This is a repository-tooling/artifact-format change with no runtime/deployment environment of its own: it affects the shape of `cadre select`'s local CLI output and any archived copies of that output (e.g. under a project's own `agents/orchestration/runs/`-style evidence trail). It does not touch Proxmox, Talos, Kubernetes, or any production/staging surface; `agent-autonomy.yaml`'s `mutations` approval tiers for persistent/staging/production environments do not apply to this backlog item's scope. If a future design phase proposes anchoring provenance to an external system (e.g. a signing service or ledger), that would introduce a new environment dependency this record does not currently assume or authorize — see OD-4.

## 8. Assumptions

Labeled explicitly per this role's required behavior, distinguished from approved fact:

- **A-1:** The backlog's P1 priority for idea #7, and its "pairs with #8" dependency note, remain valid as prior product-intent-agent framing from 2026-07-28 and are not re-decided here — but see Section 0's correction that #8 has not actually shipped, which this record treats as new grounding, not a re-litigation of priority.
- **A-2:** "Provenance binding" is read as "an auditor can verify which suite-input content produced a given plan," consistent with the backlog's stated beneficiary (auditors/reviewers) and with this repository's existing `dispatch_fingerprint`/`generated_at` fields being the closest existing analogs. It is not read as a broader claim about binding *agent execution* provenance (e.g. which specific model/runner session executed the plan) — that would be a materially different, unaddressed problem and is not assumed in scope. See OD-7.
- **A-3:** The gap this intent addresses (self-consistency fingerprint vs. suite-state binding) is real and current regardless of whether idea #8/#6 ship first — i.e., this intent is not blocked on #8 shipping, since even catalog.yaml/routing.yaml-only binding (no overlay, no runner-capability manifest) would close a meaningful part of the gap. Sequencing (whether to build the catalog/routing binding now and extend it later, versus waiting for #8/#6 to land first) is left to requirements/design, not decided here.
- **A-4:** "Auditors/reviewers" as named beneficiaries are assumed to include both roles internal to this repository's own Cadre role catalog (e.g. `security-reviewer`) and external human reviewers in a consuming project's governance process; no source document narrows this further.

## 9. Conflicts

No conflicting objectives were found between this intent and other read sources. One material discrepancy, not a policy conflict, is called out prominently in Section 0: the dispatch instruction for this task asserted idea #8 was "now shipped," and grounding found it is not. This is recorded as OD-1, not treated as a conflict between policies or stakeholders. Separately, the pre-existing, unrelated idea #16 conflict (`team-profile.yaml`'s `source_control.platform: github` vs. `cicd.platform: gitlab_ci`) is cross-referenced only, per the same convention the idea #10 intent record used, since it is orthogonal to this idea's subject matter.

## 10. Success criteria (measurable, not target-inventing)

Per this role's constraint against inventing targets/commitments/priorities, these are framed as observable conditions the eventual requirements/design/build phases can verify against, not as pass/fail numeric SLAs this record is authorized to set:

- **SC-1:** Given an archived historical dispatch plan artifact and independent access to this repository's history (or a consuming project's copy of the suite), a reviewer can determine exactly which content of `agents/catalog.yaml` and `agents/orchestration/routing.yaml` produced that plan, without needing to trust an unverifiable claim embedded by the same process that generated the plan.
- **SC-2:** If `agents/catalog.yaml` or `agents/orchestration/routing.yaml` is subsequently edited, an archived plan generated before the edit remains distinguishable, via the provenance mechanism, from a plan that would be generated after the edit — i.e., the binding changes when a materially relevant input changes, and does not silently continue to look identical.
- **SC-3:** The relationship between the new provenance mechanism and the existing `dispatch_fingerprint` field is explicit and documented (e.g. in `selection.schema.json` and/or `RUNBOOK.md`), not left ambiguous as to which field answers "is this plan internally self-consistent" versus "what suite state produced this plan."
- **SC-4:** Once idea #8 (runner-capability manifest) and idea #6 (routing overlay) exist, the provenance mechanism's design is extensible to cover them without requiring a breaking redesign of the mechanism chosen for catalog/routing — demonstrable by the requirements/design phase explicitly considering both companion features' eventual shape, even though neither is built by this intent.
- **SC-5:** The mechanism does not require an auditor to re-run `cadre select` and re-trust its live output as the standard of truth — the archived artifact plus independently accessible suite-state evidence (e.g. git history) is sufficient, consistent with constraint C-2.

Numeric targets (e.g. specific hash algorithm, signing scheme, artifact-size budget) are intentionally not set here — they are a requirements/design decision per this role's constraint against inventing commitments.

## 11. Open-decision register

| ID | Decision needed | Accountable owner | Status | Notes / linked source |
|----|------------------|--------------------|--------|------------------------|
| OD-1 | Confirm whether idea #8 (runner-capability manifest) and idea #6 (routing overlay) are actually planned/in-flight, and correct the backlog/dispatch record if the "now shipped" framing was premature or based on a different branch/worktree state | Human — unnamed; likely whoever maintains `requirements.md`'s priority table | **Should be resolved before requirements decomposition for #7 begins** | Grounded finding, Section 0: neither `agents/runner-capabilities.json` nor `agents/orchestration/src/routing_overlay.py` exist in this repository as of 2026-07-29; most recent shipped backlog work per `git log` is idea #10 (`a566ebc`). |
| OD-2 | Name the accountable Product Owner for this repository's own feature backlog | Human — unnamed | **Blocking G1 approval** | Same gap already logged as OD-1 in the sibling idea #10 intent record; not re-resolved here, restated for this record's own completeness. |
| OD-3 | Implementation mechanism: git-commit-SHA binding vs. per-file content hash(es) vs. signed attestation vs. reference to an external evidence/ledger store vs. some combination | Requirements/design phase | Open, non-blocking for intent | Explicitly out of this role's authority (C-1). The task instruction itself named these as illustrative options not to be decided here. |
| OD-4 | Verifiability strength: plain recorded/inspectable value vs. cryptographically signed attestation, and whether any external signing/anchoring service becomes a new environment dependency | Requirements/design phase; security-reviewer input likely warranted given "auditor" framing | Open, non-blocking for intent | Affects both Section 6 (C-5 dependency review) and Section 7 (environment scope). |
| OD-5 | Whether the new provenance field(s) become schema-required in `selection.schema.json` (like today's `dispatch_fingerprint`) or optional/advisory | Requirements/design phase | Open, non-blocking for intent | `selection.schema.json`'s current `required` array includes `dispatch_fingerprint`; extending that precedent to a new field is a scope decision, not decided here. |
| OD-6 | Whether binding the external `agentic-sdlc` lifecycle-contract version (used when `lifecycle_tracking.status == "integrated"`) is in scope for this backlog item or a separate future item | Requirements-agent, respecting the repo-boundary constraint (C-4) that Cadre must not become authoritative for another project's gate semantics | Open, non-blocking for intent | Section 3 names this as a related but distinct gap; Cadre may record which kernel version contributed inputs without asserting gate authority. |
| OD-7 | Confirm "provenance" is scoped to suite-input state (catalog/routing/overlay/manifest), not agent-execution/runtime provenance (which model/session actually executed the dispatched plan) | Requirements-agent | Open, non-blocking for intent | Assumption A-2 states this record's reading; a materially different intent record would be needed if the backlog author meant execution provenance instead. |
| OD-8 | Whether golden-corpus / other existing consumers of dispatch-plan output (e.g. item B's fixture harness, which already normalizes/excludes `dispatch_fingerprint` from comparison per `requirements.md`) need equivalent normalization rules for any new provenance field | Requirements/design phase | Open, non-blocking for intent | Directly analogous to how `dispatch_fingerprint` and `generated_at` are already excluded from golden-corpus comparison; a new field with similarly run-dependent content would need the same treatment. |

## 12. Knowledge retrieval status

Not used for this pass. Consistent with the prior product-intent-agent framing pass for the same backlog (`requirements.md` header: "Knowledge retrieval: not used for this ideation/requirements pass (ad hoc dispatch, not selector-driven)") and with the sibling idea #10 intent record's same disposition, this dispatch was likewise ad hoc rather than selector-driven, so no pre-dispatch retrieval occurred per `knowledge-use-policy.md`. No material decision in this record depends on unavailable or conflicting knowledge-store content — all claims here trace to files read directly from the repository (cited by path throughout) and to `git log` output, both reproducible by any reviewer with repository access. Follow-up retrieval remains available if a future revision of this record needs it.

---

## Handoff

This record is ready for G1 Intent Gate review by the (currently unnamed — see OD-2) human Product Owner. It is not ready for requirements decomposition to begin treating OD-1 and OD-3–OD-8 as resolved; those remain open decisions for the requirements/design phase to carry forward and, where relevant, escalate further. OD-1 in particular should be resolved first, since it affects whether idea #7's requirements phase should proceed now against catalog/routing binding alone, or wait for ideas #6/#8 to land.
