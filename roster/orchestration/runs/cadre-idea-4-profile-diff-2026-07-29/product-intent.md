# Product Intent Record — Profile drift/re-sync report (`cadre profile diff`)

**Intent ID:** `INTENT-CADRE-BACKLOG-4`
**Revision:** 1 (initial)
**Status:** draft — awaiting human Product Owner review at G1
**Author (agent):** product-intent-agent
**Date:** 2026-07-29
**Repository:** `/home/deagy/sdk/cadre`
**Classification:** internal
**Source backlog item:** `agents/orchestration/runs/cadre-feature-backlog-requirements-2026-07-28/requirements.md`, priority table row #4 ("Profile drift/re-sync report (`cadre profile diff`)" — P1 — Beneficiary: Consuming-project leads — Dependency: none). Priority (P1) and "no dependency" sequencing were set by the prior product-intent-agent framing pass (2026-07-28) and are carried forward here as approved context, not re-decided by this record — see "Explicitly not decided here." That table gave no further detail beyond the one-line idea; this record grounds the problem in the actual mechanism the idea would apply to, per dispatch instruction.

---

## 1. Owner

**Accountable Product Owner:** not named in any source document read for this record. As already logged against the sibling idea-10 intent record (`agents/orchestration/runs/cadre-idea-10-schema-validation-2026-07-29/product-intent.md`, OD-1), `agents/shared/team-profile.yaml`'s `out_of_scope_standards` block names Daniel Eagy as Product Owner only for one specific, unrelated compliance-scope decision (2026-07-26); nothing in the backlog, `AGENTS.md`, or `RUNBOOK.md` designates a Product Owner for this repository's own feature backlog generally. Logged again here as OD-1 rather than assumed resolved, since this is a distinct intent record and the prior escalation does not automatically carry forward as "answered."

**Working owner for this intent record's authorship:** product-intent-agent (this agent), acting on the orchestrator's dispatch instruction naming idea #4. Authorship does not confer approval authority — see this role's Authority section.

## 2. Users / beneficiaries

Restating the backlog's own beneficiary line ("Consuming-project leads"), traced to concrete artifacts and roles rather than left generic:

- **Leads of projects that adopted this suite's Secure Cloud provider profile** via `cadre sdlc init --root <path> --profile secure-cloud` (`agents/RUNBOOK.md` §16; `docs/lifecycle-and-plugin-operations.md`). Per `RUNBOOK.md`: *"generated project wrappers are static copies bound to that provider version"* — the target project's `.agentic-sdlc/` records are a point-in-time copy of `plugins/cadre/provider.json` and `plugins/cadre/profiles/secure-cloud/profile.json`, not a live link back to this checkout. These are the people who would want to know, later, whether that copy is stale.
- **Engineering leads / maintainers inside a consuming project** who own that project's local `.agents/shared/*` overlays (`agents/shared/README.md`) and would need to reconcile both the provider-profile copy and any shared-policy overlay against this suite's current defaults.
- **This suite's own maintainers**, indirectly: a working drift report reduces support burden from consuming projects asking "are we current?" without a repeatable way to answer it themselves, and gives maintainers a released-artifact-shaped signal (analogous to `cadre version --check`, `agents/orchestration/src/plugin_version.py`) for whether a given provider/profile release is still compatible with a given consumer's lock record.

## 3. Problem statement (WHAT and WHY)

This suite supplies a "provider profile" into consuming projects through two related but distinct mechanisms, and neither currently has a re-sync/drift check:

- **The Secure Cloud provider profile proper** — `plugins/cadre/provider.json` (`id: "cadre"`, `version: "0.3.0"`, `kernel_compatibility.minimum`/`maximum_exclusive`, `profile_roots: ["profiles"]`) and `plugins/cadre/profiles/secure-cloud/profile.json` (`id: "secure-cloud"`, its own `version`, `extends: "generic"`, the `agents`, `routing`, and `impact_categories` it supplies). `cadre sdlc init --root /path/to/target --profile secure-cloud` (`RUNBOOK.md` §16, `docs/lifecycle-and-plugin-operations.md`) writes a **static copy** of this material, bound to the provider version at initialization time, into the target project's own `.agentic-sdlc/` records — which that project then owns (`docs/lifecycle-and-plugin-operations.md`: *"The target project owns its `.agentic-sdlc/` records and consequential decisions"*). `RUNBOOK.md` §16 separately instructs operators to *"Run the plugin `validate` command and preserve the version lock with the reviewed overlay"* and, on upgrade, to *"reinstall the plugin, inspect lifecycle/schema changes, validate existing records, migrate incompatible records explicitly, and update the project version lock only with the reviewed overlay change."* This describes a manual, human-driven re-sync procedure; no tooling in this repository (per `bin/subcommands.tsv`: `select`, `knowledge`, `generate-plugin`, `generate-authority-aides`, `generate-role-metadata`, `bootstrap-codex`, `version`, `resolve-shared`, `mcp-dispatch-server`, `init` — no `profile` entry) currently reports, automatically or on request, whether a given consuming project's locked provider/profile version has fallen behind this suite's current `provider.json`/`profile.json`, or in what way.
- **`agents/shared/*` global policy defaults** — a related but mechanistically different case. `agents/shared/README.md` and `resolve.py` already provide a **live** resolution mechanism (`cadre resolve-shared <filename>`): a project's `.agents/shared/<filename>` overlay is deep-merged (or, for prose, appended) against this checkout's *current* `agents/shared/<filename>` default at resolve time, walking up to the nearest `.git`. Because this always reads the live default rather than a point-in-time copy, there is no independent "is my copy stale" question for `resolve-shared` output itself in the way there is for the provider-profile static copy — the open question there is instead whether the consuming project has *this checkout* available to resolve against at all (a separate, already-documented precondition), not whether a snapshot has drifted.

**Consequence today:** a consuming-project lead whose project was initialized against, say, `provider.json` `version: "0.3.0"` has no way to determine, without manually diffing `plugins/cadre/provider.json` / `plugins/cadre/profiles/secure-cloud/profile.json` against their project's own `.agentic-sdlc/` records by hand, whether their project is (a) running current policy, (b) running a stale-but-otherwise-unmodified copy of an older provider/profile version, or (c) running a copy that a project maintainer has since hand-edited/customized and that has therefore diverged from *both* the version it was copied from and this suite's current default — three materially different situations that call for different responses (routine upgrade, no action, or a deliberate reconciliation of a local customization against upstream changes), none of which are currently distinguishable without manual inspection.

**Desired outcome:** a consuming-project lead, or this suite's own maintainers on behalf of a consuming project, can run a repeatable check that reports which of the above three states a given project's copied provider/profile material is in, relative to this suite's current release, without that check itself deciding what to do about it (upgrade, ignore, or reconcile) or applying any change.

## 4. Scope

In scope for this intent (the *problem space* this backlog item addresses — not an implementation mandate):

- Detecting and reporting drift between a consuming project's copied `.agentic-sdlc/`-recorded provider/profile material (originating from `plugins/cadre/provider.json` and `plugins/cadre/profiles/secure-cloud/profile.json`, or `profiles/generic/profile.json` for non-Secure-Cloud adopters) and this suite's current released versions of the same artifacts.
- Distinguishing, per the problem statement, at least the three states: current (no drift), stale-unmodified (behind current version, no local customization), and diverged (locally modified, independent of whether it's also behind).
- Reporting scoped to what changed at a level useful to a lead deciding whether to re-sync — e.g., which agents were added/removed from the profile's `agents` list, which `routing` entries changed, `kernel_compatibility` range changes — without this intent record prescribing the exact report format or granularity (a requirements/design decision).
- Framing whether this idea's scope should also cover `agents/shared/*` overlay staleness (as opposed to just the provider/profile static copy) is explicitly logged as an open decision (OD-4) rather than assumed in or out, since the beneficiary language ("re-sync report") and the existing `resolve-shared` precedent are both plausibly relevant but mechanistically different, per Section 3.

## 5. Exclusions (explicitly out of scope for this intent)

- **Implementation approach is not decided here.** Whether this ships as a new `cadre profile` subcommand family (as the backlog title's literal `cadre profile diff` suggests), an extension of the existing `cadre version --check` tool (`agents/orchestration/src/plugin_version.py`), an extension of `cadre resolve-shared`, or something else is a requirements/design decision, per this role's authority limits.
- **Where the check reads the consuming project's "current locked version" from is not decided here.** `RUNBOOK.md` describes a human-maintained "version lock" concept (*"preserve the version lock with the reviewed overlay"*) but does not specify a file format or location owned by this repository — the target project's `.agentic-sdlc/` records are owned and validated by the separate `deagy/agentic-sdlc` kernel, per this repository's own permanent two-repo boundary (`CLAUDE.md`: *"cadre/... does not run its own `.agentic-sdlc/` overlay and never becomes authoritative for another project's gate approvals"*). Whether a `cadre profile diff` tool reads that kernel-owned state directly, requires the kernel's own `validate`/inspection output as an input, or is scoped to comparing two profile artifacts supplied by the caller (no kernel read at all) is unresolved and directly implicates that boundary — see OD-2.
- **No decision on whether drift reporting also covers `agents/shared/*` overlays** (see Section 4's note) — logged as OD-4, not resolved here.
- **No decision on automatic re-sync/remediation.** `docs/lifecycle-and-plugin-operations.md` is explicit that *"Generated output is a distribution artifact; it does not become a new source of authority"* and *"Plugin upgrades never grant approval or rewrite project decisions automatically."* This intent's outcome is a *report*; applying any change to a consuming project's records is out of scope for this idea and, per the cited policy, would in any case need to remain a separate, human-reviewed action regardless of how this idea is eventually built.
- **No decision on cadence, automation trigger, or CI integration** (e.g., whether this becomes a scheduled check, a manual on-demand command, or something a consuming project's own CI runs) — a requirements/process decision.
- **No performance, tooling, or new-dependency commitments.**

## 6. Constraints

Traced to existing approved repository policy and code, not invented:

- **C-1 (`CLAUDE.md`'s permanent two-repo boundary, restated in `agents/RUNBOOK.md` and `docs/lifecycle-and-plugin-operations.md`):** this suite must not become authoritative for another project's gate approvals, lifecycle records, or version-lock state. A drift *report* is consistent with this; anything that writes to or overrides a consuming project's `.agentic-sdlc/` records is not, and is excluded per Section 5.
- **C-2 (`agents/shared/agent-autonomy.yaml`, `governance` block):** `approve_own_work: never`, `authorize_production_release: never`. A profile-diff report must not be framed as, or double as, an approval or authorization signal for upgrading a consuming project.
- **C-3 (`docs/lifecycle-and-plugin-operations.md`):** *"Generated output is a distribution artifact; it does not become a new source of authority"* and *"Plugin upgrades never grant approval or rewrite project decisions automatically."* Any eventual tool must present drift as information, not as a mutation or an implicit recommendation to act.
- **C-4 (`agents/shared/operating-principles.md`):** findings must be evidence-based and precisely located (matching this repo's established convention in `routing_health.py` and `test_repository_health.py`), not a generic "drift exists / does not exist" signal.
- **C-5 (this role's authority limit):** this record may not decide implementation, CLI surface, file formats, or process integration — only the problem, desired outcome, and open questions.

## 7. Environments

This is a cross-project tooling concern rather than a runtime/deployment one: it operates on this repository's release artifacts (`plugins/cadre/provider.json`, `plugins/cadre/profiles/*/profile.json`) on one side, and a consuming project's local, human-owned lifecycle records on the other. It does not touch Proxmox, Talos, Kubernetes, or any production/staging surface in either repository; `agent-autonomy.yaml`'s `mutations` approval tiers for persistent/staging/production environments do not apply to this backlog item's own scope, though C-1/C-3 above constrain how its *output* may be used by a consuming project afterward.

## 8. Assumptions

Labeled explicitly per this role's required behavior, distinguished from approved fact:

- **A-1:** The backlog's "Profile drift/re-sync report" idea is read as concerning the Secure Cloud **provider profile** mechanism (`provider.json` / `profiles/secure-cloud/profile.json`, copied via `cadre sdlc init --profile secure-cloud`) as its primary subject, based on the CLI name given in the backlog (`cadre profile diff`) matching that mechanism's own vocabulary (`--profile secure-cloud`, `profile_roots`, `profiles/secure-cloud/profile.json`) rather than the `agents/shared/*` overlay mechanism, which already has its own live-resolution tool (`resolve-shared`) with different mechanics. This is stated as a reading, not a scope decision — see OD-4.
- **A-2:** The backlog's P1 priority and "no dependency" note for idea #4 remain valid as prior product-intent-agent framing from 2026-07-28 and are not re-decided here.
- **A-3:** "Drift" is read broadly enough to include both "behind current version, unmodified" and "locally diverged," per Section 3's three-state framing, rather than narrowly as version-number staleness alone — because a consuming project is documented (`agents/shared/README.md`) as being permitted to customize its local overlay, and nothing in the read sources suggests provider/profile copies are meant to be immutable once written, an assumption this record flags rather than treats as settled (see OD-3).

## 9. Conflicts

No direct conflicting objectives were found between this intent and other read sources. One structural tension is worth surfacing rather than resolving:

- **Tension between "consuming project owns its `.agentic-sdlc/` records" (`docs/lifecycle-and-plugin-operations.md`) and "this suite reports on those records' drift."** A tool that reads a consuming project's lock/record state to compute drift is reading, not writing, so it does not on its face violate ownership — but the *implementation* choice of where that tool lives (in this repository, in the `deagy/agentic-sdlc` kernel, or split across both) directly engages the permanent two-repo boundary this repository is bound by (`CLAUDE.md`). This record does not resolve which side of the boundary should own the comparison logic; it flags the tension as OD-2, since resolving it is a design decision this role is not authorized to make.

## 10. Success criteria (measurable, not target-inventing)

Per this role's constraint against inventing targets/commitments/priorities, these are framed as observable conditions the eventual requirements/design/build phases can verify against, not as numeric SLAs this record is authorized to set:

- **SC-1:** Given a consuming project initialized against a known-older `provider.json`/`profile.json` version and left otherwise unmodified, the report identifies it as behind-current (not merely "different"), and names what changed (e.g., which `agents`, `routing` entries, or `kernel_compatibility` bounds differ) — demonstrable via a fixture pairing an older and current profile snapshot.
- **SC-2:** Given a consuming project whose copied provider/profile material has been hand-edited since initialization, the report distinguishes that state (locally diverged) from simple version staleness, per Section 3's three-state framing — demonstrable via a fixture with a modified copy at the same version as current.
- **SC-3:** Given a consuming project whose copied material exactly matches this suite's current released provider/profile artifacts, the report returns a clean/no-drift result with no false positives.
- **SC-4:** The report is read-only against both this repository's release artifacts and the consuming project's records — running it produces no mutation to either side (traced to C-1/C-3).
- **SC-5:** Findings are located precisely enough (which field, which artifact, old value vs. new value) that a consuming-project lead can act on the report without needing to separately hand-diff the underlying JSON files themselves (traced to C-4).

Numeric targets (e.g., runtime budget, CLI exit-code contract, exact output format) are intentionally not set here — they are a requirements/design decision per this role's constraint against inventing commitments.

## 11. Open-decision register

| ID | Decision needed | Accountable owner | Status | Notes / linked source |
|----|------------------|--------------------|--------|------------------------|
| OD-1 | Name the accountable Product Owner for this repository's own feature backlog | Human — unnamed | **Blocking G1 approval** | Same gap already logged against the sibling idea-10 intent record; not resolved by that prior escalation, restated here since this is a separate record. |
| OD-2 | Where the drift-comparison logic and its "current locked version" input should live, given the permanent two-repo boundary between this repository and `deagy/agentic-sdlc` (`CLAUDE.md`) — this repo compares against a caller-supplied/kernel-exposed record only, vs. the kernel itself grows a comparison feature and this repo just supplies the release artifacts to diff against, vs. some split | Requirements/design phase, informed by `deagy/agentic-sdlc` maintainers since it touches their owned `.agentic-sdlc/` record format | Open, non-blocking for intent, but architecturally consequential | Directly engages `CLAUDE.md`'s "cadre... never becomes authoritative for another project's gate approvals" invariant; this role is not authorized to resolve it. |
| OD-3 | Whether "drift" in scope for this idea includes locally-customized/diverged profiles (not just version staleness), and if so how "customized" is distinguished from "corrupted" or "invalid" | Requirements-agent | Open, non-blocking for intent | Flagged as Assumption A-3; the read sources establish that overlay customization is a supported pattern for `agents/shared/*` but do not explicitly confirm the same is true for the provider/profile copy itself. |
| OD-4 | Whether this idea's scope also covers `agents/shared/*` overlay drift (in addition to, or instead of, the provider/profile static-copy case), given `resolve-shared` already provides live (non-snapshot) resolution for that mechanism and the two are not the same kind of drift problem | Requirements-agent | Open, non-blocking for intent | Assumption A-1 states this record's reading (provider/profile is primary subject) but does not foreclose requirements-agent scoping it more broadly. |
| OD-5 | Report format, delivery mechanism (CLI subcommand `cadre profile diff` as literally named in the backlog, vs. extending `cadre version --check`, vs. something else), and whether it becomes a CI-integrated check or stays on-demand | Requirements/design phase | Open, non-blocking for intent | Explicitly out of this role's authority (C-5). |
| OD-6 | Whether a "current" release baseline to diff against means this checkout's working tree, the latest tagged release, or a specific version the caller names | Requirements-agent | Open, non-blocking for intent | Not addressed in any read source; relevant because `plugin_version.py`'s existing `cadre version` already distinguishes "current" (working tree) from tagged releases for a related but different purpose. |

## 12. Knowledge retrieval status

Not used for this pass. Consistent with the prior product-intent-agent framing pass for the same backlog (`requirements.md` header: "Knowledge retrieval: not used for this ideation/requirements pass (ad hoc dispatch, not selector-driven)") and with the sibling idea-10 intent record's precedent, this dispatch was likewise ad hoc rather than selector-driven, so no pre-dispatch retrieval occurred per `agents/shared/knowledge-use-policy.md`. No material decision in this record depends on unavailable or conflicting knowledge-store content — all claims here trace to files read directly from this repository, cited by path throughout (`agents/RUNBOOK.md`, `docs/lifecycle-and-plugin-operations.md`, `CLAUDE.md`, `plugins/cadre/provider.json`, `plugins/cadre/profiles/secure-cloud/profile.json`, `agents/shared/README.md`, `agents/orchestration/src/resolve.py`... see inline citations). Follow-up retrieval remains available if a future revision of this record needs it.

---

## Handoff

This record is ready for G1 Intent Gate review by the (currently unnamed — see OD-1) human Product Owner. It is not ready for requirements decomposition to begin treating OD-2–OD-6 as resolved; those remain open decisions for the requirements/design phase to carry forward and, where relevant (OD-2 in particular), escalate to `deagy/agentic-sdlc` maintainers given the cross-repository boundary it touches.
