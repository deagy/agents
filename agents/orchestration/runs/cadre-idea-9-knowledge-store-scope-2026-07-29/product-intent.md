# Product Intent Record — Enforced Knowledge-Store Scope

**Intent ID:** `INTENT-CADRE-IDEA-9-KS-SCOPE`
**Revision:** `1.0` (initial)
**Status:** draft — awaiting Product Owner review at G1 Intent Gate; **not yet cleared for design/build**
**Classification:** internal
**Author role:** `product-intent-agent`
**Date:** 2026-07-29
**Repository:** `/home/deagy/sdk/cadre`
**Traces to:** `agents/orchestration/runs/cadre-feature-backlog-requirements-2026-07-28/requirements.md`, priority table row #9 ("Enforced knowledge-store scope" — P1, escalating to P0 at a second consumer — beneficiary: Knowledge-store steward — dependency: steward sign-off required)

---

## 1. Problem statement (grounded, not hypothetical)

**Source of the gap (inspected directly, not inferred):**

- `agents/knowledge-store/src/cli.py` defines `--source` as an **optional, unvalidated, caller-supplied string** on every command that reads it:
  - `search` (`search.add_argument("--source")`) — no default, no requirement.
  - `context` (`context.add_argument("--source")`) — no default, no requirement.
  - `ingest` (`ingest.add_argument("--source", default="chat-export")`) — has a default, but that default is a generic placeholder, not a project identity.
- `agents/knowledge-store/src/config.py` (`default_config_path`, `find_project_local_config`) resolves scope purely by **which config file happens to be discovered on disk** at invocation time (project-local `.agents/knowledge-store/config.json` walking up to the `.git` boundary, else the single machine-wide `$KNOWLEDGE_STORE_HOME` store). There is no code path that authenticates a caller, ties a caller identity to a permitted `--source`/project, or rejects a query for lacking one.
- Classification filtering (`README.md` line 35, `SECURITY.md` "Known limitations") is **exact-match on a caller-supplied string**, applied before ranking — it is explicitly documented as "not production authorization," not an enforced boundary.
- The one place `--source` is populated automatically today is `cadre select`'s own internal invocation path (`agents/orchestration/src/build_dispatch_plan.py`, lines ~300 and ~465), which derives it from the target repository's origin slug. That convenience is scoped to `cadre select`'s own call sites only — it is not a property of the knowledge-store CLI itself, so any other caller (a hand-run `agents knowledge search`/`context` invocation, a differently-integrated agent runner, or a future non-`cadre select` consumer) gets no such derivation and no enforcement if it omits `--source`.

**Net effect:** against the shared global store (the default for any project without its own `.agents/knowledge-store/config.json`), a retrieval call that omits `--source` — whether by oversight, a caller that doesn't know the convention, or a future integration that never goes through `cadre select` — is not rejected, warned, or narrowed. It ranks and returns matching content across **every project that shares that store**, filtered only by a caller-supplied `classification` string with no verification that the caller is authorized to assert that classification. `README.md` and `SECURITY.md` already state this plainly as an accepted, documented design tradeoff ("this is deliberate," "not production authorization," "caller supplied... not authentication") rather than an unknown defect — the gap is that the tradeoff currently has **no enforcement mechanism at all**, only a documentation-and-convention expectation (`SECURITY.md`'s "always filter retrieval by that same `--source`," the `knowledge-ingestion` skill's workflow step 7, and `knowledge-store-steward`'s `AGENT.md` "verify... every ingestion... carries a project-identifying `--source`") that depends entirely on every caller, present and future, remembering and complying.

**Distinct from remaining-backlog item #1:** `requirements.md`'s remaining-17-items list, item #1 ("Knowledge-focus completeness check") is a *routing-configuration* check — whether every catalog agent selected by `routing.yaml` has a `knowledge_focus` entry, verified statically. It says nothing about, and does not narrow, the knowledge-store's own retrieval/ingestion scope enforcement. This intent record does not restate or subsume item #1; the two are about different layers (routing metadata completeness vs. data-access boundary enforcement).

## 2. Owner

- **Accountable Product Owner:** not yet named in any source read for this intent record. `requirements.md`'s backlog table lists the *beneficiary* as "Knowledge-store steward," not an accountable Product Owner — those are different roles (see Open Decision OD-1).
- **Operationally accountable role once approved:** `knowledge-store-steward` (`agents/knowledge-store/AGENT.md`) is the role whose `Required checks` and `Escalate when` sections already name this exact gap class ("Keep classifications and tenant boundaries enforceable before similarity ranking," "Tenant separation cannot be enforced" as an escalation trigger) — but see §6 and Open Decision OD-2 for the limits of that role's authority.

## 3. Intended users / beneficiaries

- **Primary beneficiary (per backlog table):** Knowledge-store steward — the role currently expected to manually verify `--source` discipline across every ingestion and retrieval call, with no structural backstop.
- **Secondary beneficiaries:**
  - Any project/consumer relying on the shared global store (`$KNOWLEDGE_STORE_HOME`) whose classified or project-scoped content could otherwise be exposed to a differently-scoped caller.
  - Agents and downstream reviewers who consume `context` bundles and rely on the `trust`/`classification`/citation fields being scoped correctly to the calling task.
  - Future second-and-later consumer projects — the backlog table's own priority note ("→P0 at 2nd consumer") signals that risk compounds as more projects share the default store.

## 4. Desired outcome (WHAT, not HOW)

A caller of the knowledge store's retrieval or ingestion commands cannot, through omission, unfamiliarity with convention, or a future non-`cadre select` integration path, cause content to cross a project/tenant boundary it was not authorized to reach — **without this record deciding which specific mechanism achieves that** (see §8, explicitly out of scope for this intent record).

This is an outcome about **closing an enforcement gap**, not a request to change the documented default topology (single shared store vs. per-project store) — see Open Decision OD-4 for why that distinction itself needs Product Owner confirmation before design proceeds.

## 5. Scope

In scope for the eventual requirements/design work this intent record hands off to:

- The boundary-enforcement gap between "documented convention" and "structural guarantee" for `--source` (and, subject to Open Decision OD-5, `classification`) on `agents knowledge search` and `agents knowledge context`.
- The same gap on `agents knowledge ingest`, where an omitted or incorrect `--source` writes content under a misleading project identity into the shared store.
- Any caller of these commands, not just `cadre select` — including hand-run CLI invocations, the `knowledge-ingestion` skill's workflow, and any other current or future agent-runner integration.
- The shared global store (`$KNOWLEDGE_STORE_HOME`) specifically, since project-local stores (`.agents/knowledge-store/config.json`) already achieve a **real partition** (a separate database) rather than relying on a filter — that existing mechanism is not itself broken; this intent is about the shared-store case where isolation is documented as filter-dependent, not database-dependent.

## 6. Exclusions (explicitly not this intent's authority to decide)

- **Does not decide the enforcement mechanism.** Whether the fix is a mandatory `--source` flag, deriving `--source` automatically for every caller the way `cadre select` already does for its own calls, hierarchical/authenticated classification, authenticated caller identity, CI-level linting, or some other approach is a design decision for a later stage, not this record.
- **Does not decide priority or scheduling** relative to the rest of the backlog (`requirements.md`'s table already assigns P1→P0-at-second-consumer; this record does not revise that).
- **Does not decide whether the shared-global-store-by-default topology itself should change** — that is a materially different, larger decision (see Open Decision OD-4) than closing the enforcement gap in the filter that topology currently relies on.
- **Does not accept risk, grant a policy exception, or authorize production use of any resulting mechanism** — per `agents/shared/agent-autonomy.yaml`'s `governance` block, no agent role (including `knowledge-store-steward`) may do so; those remain human Product Owner / accountable-approver actions.
- **Does not implement or design retention/deletion lifecycle commands** — `SECURITY.md`'s "Known limitations" and `README.md` already document these as unimplemented in the demo; that is a separate, already-acknowledged gap, not part of this intent unless the Product Owner explicitly folds it in.
- **Does not evaluate or select an authentication mechanism for callers** — `SECURITY.md` and `README.md` both state current classification/source filtering is not authentication; whether/how to add real caller authentication is a larger security-architecture decision outside this intent's authority.

## 7. Constraints

- Must remain compatible with `agents/shared/knowledge-use-policy.md` and `agents/knowledge-store/SECURITY.md`, both of which already state the two-mechanism model (real per-project partition via project-local config, or `--source`-filtered shared store) as the accepted baseline — any resulting design should close the enforcement gap in that model, not silently replace the model itself, unless the Product Owner decides otherwise (Open Decision OD-4).
- Must preserve existing citation/provenance fields (`source`, `conversation_id`, `message_id`, `chunk_id`, `content_hash`, `created_at`, `classification`) and the `agent-context.schema.json` / `canonical-message.schema.json` contracts unless a schema version bump is explicitly proposed and reviewed.
- Must not weaken the existing fail-closed behavior for missing explicit `--config` (`config.py`'s `load_config` already raises `FileNotFoundError` for a missing explicit path) — per this repo's `agents/shared/operating-principles.md`, do not silently weaken existing controls.
- Must respect `agents/shared/agent-autonomy.yaml`: `knowledge_store.ingest_update_reclassify_or_delete: knowledge_store_steward_only`; any enforcement design must not grant ordinary agents new mutation or lifecycle authority as a side effect.
- `--top` is already capped 1–20 (`SECURITY.md`) and out of scope to revisit here.

## 8. Environments

- Applies to the knowledge store as deployed today: local-first, SQLite-backed, invoked via `bin/cadre knowledge ...` / `agents knowledge ...` from any working directory, against either a project-local database or the single shared `$KNOWLEDGE_STORE_HOME` database.
- Applies identically regardless of embedding provider (`hashing` demo default or `openai-compatible`) — the scope-enforcement gap is orthogonal to embedding provider choice.
- No separate staging/production environment exists for the knowledge store today per the read sources; `SECURITY.md` describes this explicitly as a demo whose production posture (authentication, retention/deletion, encryption at rest) is not yet built out. This intent record does not assume a production environment exists yet.

## 9. Assumptions (labeled, not verified beyond what was read)

- **Assumption A1:** The backlog table's "→P0 at 2nd consumer" trigger means a second *project* (beyond this repository, "Cadre" itself) begins relying on the shared `$KNOWLEDGE_STORE_HOME` store — not a second *agent* within this same repository. Not confirmed in any source read; flagged as Open Decision OD-6.
- **Assumption A2:** "Enforced" in the idea title refers to structural/mechanical enforcement (code that rejects or narrows an unscoped call), consistent with how `SECURITY.md` and the `knowledge-store-steward` `AGENT.md` already describe the target state ("Keep classifications and tenant boundaries enforceable... before similarity ranking") — not merely stronger documentation or an added lint warning. Not confirmed; if the Product Owner intends a lighter-weight documentation/process fix, scope and success criteria below would need revision.
- **Assumption A3:** This intent record's classification (`internal`) follows the same classification used by the antecedent `cadre-feature-backlog-requirements-2026-07-28` run this idea traces to; no classification was independently specified for idea #9.

## 10. Conflicts identified

- **Documented-tradeoff vs. backlog-item framing:** `README.md` and `SECURITY.md` describe the current shared-store-plus-`--source`-filter model as a *deliberate* design choice ("This is deliberate: it lets agents retrieve cross-project context... without every project needing to set anything up"), not an oversight. The backlog item's framing ("Enforced knowledge-store scope") could be read either as (a) closing the enforcement gap within that accepted model, or (b) revisiting the model itself. This record adopts reading (a) per Assumption A2/A4 but flags the ambiguity rather than resolving it — see Open Decision OD-4.
- **No conflicting approved facts were found** across `README.md`, `SECURITY.md`, `config.example.json`, the two JSON schemas, `AGENT.md`, and the `knowledge-ingestion` skill — all consistently describe the same current-state gap (caller-supplied, non-enforced `--source`/classification) without internal contradiction.

## 11. Measurable success criteria (outcomes, not implementation)

Success criteria are stated as observable outcomes; they intentionally do not name a mechanism.

1. **SC-1:** For every command that currently accepts an optional `--source` on the shared global store (`search`, `context`, `ingest`), a retrieval or ingestion call that omits project-scope information no longer silently succeeds and returns/writes content across an unintended project boundary — outcome is measurable by a before/after test: today, a call with `--source` omitted against a populated shared store returns/writes across all `source` values in the database (reproducible against current `cli.py`); after the change, an equivalent unscoped call must either be rejected, fail closed, or be automatically and correctly scoped, not silently span projects.
2. **SC-2:** Existing documented behavior for project-local stores (real partition via `.agents/knowledge-store/config.json`) continues to hold unchanged — measurable via the existing test suite (`agents/knowledge-store/test/`) continuing to pass with no regression in project-local isolation.
3. **SC-3:** `knowledge-store-steward`'s existing manual verification duty ("verify every ingestion against the shared store carries a project-identifying `--source`," `AGENT.md` Required checks) is reduced from a fully manual check to one with at least one structural backstop — measurable by whether the steward's completion criteria can cite an automated check rather than only manual review going forward.
4. **SC-4:** No existing schema contract (`agent-context.schema.json`, `canonical-message.schema.json`), citation field, or fail-closed behavior for missing explicit `--config` regresses — measurable via the existing `agents/knowledge-store/test/` suite plus `test_repository_health.py` continuing to pass.

Explicitly not included: any numeric performance, latency, or adoption target, since no source read establishes one and inventing one would violate this role's authority.

## 12. Open-decision register

| ID | Open decision | Why it can't be resolved here | Accountable owner |
|----|----|----|----|
| OD-1 | Who is the accountable Product Owner for this intent (distinct from "Knowledge-store steward," which the backlog table lists as *beneficiary*, not decision owner)? | No source read names a Product Owner for this specific idea; `team-profile.yaml` names a Product Owner (Daniel Eagy) for the unrelated `out_of_scope_standards` compliance-framework decision only — not established as this idea's owner. | Human Product Owner (name TBD) |
| OD-2 | **Steward sign-off gating, per the task's explicit note:** this idea's backlog dependency says "steward sign-off required" — flagged here as needing `knowledge-store-steward` role review/sign-off *before design/build starts*, not merely before ship (unlike most other backlog items, which only need review before ship). Per `AGENT.md`, the steward role's authority covers operating the store and approving curated writes within approved datasets, and it must escalate when "tenant separation cannot be enforced" — it is well-positioned to confirm the gap framing and technical feasibility of enforcement options. It is **not** authorized (per `agents/shared/agent-autonomy.yaml` `governance` block: `accept_security_or_compliance_risk: never`, `grant_policy_exception: never`) to accept residual risk, grant a policy exception, or substitute for Product Owner priority/scope approval. Confirm this split (steward = technical review gate; Product Owner = priority/scope/risk-acceptance gate) before dispatching design work. | Knowledge-store steward (technical review) + Product Owner (approval) — split not yet confirmed by either |
| OD-3 | What "second consumer" means for the P1→P0 priority escalation (a second project sharing `$KNOWLEDGE_STORE_HOME`, or something else), and who tracks/detects that trigger | Not defined in any source read (see Assumption A1) | Product Owner, once named (OD-1) |
| OD-4 | Whether this idea is scoped to closing the enforcement gap within the existing documented shared-store-plus-filter model, or to revisiting the model itself (e.g., moving toward per-project stores as the default) | `README.md`/`SECURITY.md` present the current model as deliberate; the backlog item's one-line title doesn't disambiguate intensification-of-enforcement from architecture change | Product Owner, once named (OD-1) |
| OD-5 | Whether `classification` filtering (in addition to `--source`) is in scope for "enforced," given both are currently caller-supplied and unauthenticated | Backlog item title says "scope," which most directly maps to project/tenant (`--source`); classification enforcement is a related but separable gap `SECURITY.md` also documents ("Known limitations") | Product Owner, once named (OD-1) |
| OD-6 | Confirm or correct Assumption A1 (definition of "2nd consumer") and Assumption A2 (structural vs. documentation-only meaning of "enforced") | Both are inferred from context, not stated directly in the backlog table | Product Owner, once named (OD-1) |

## 13. Knowledge retrieval status

Not used for this intent-drafting pass. Per this task's instructions, grounding was drawn directly from repository source (`agents/knowledge-store/README.md`, `SECURITY.md`, `config.example.json`, `agent-context.schema.json`, `canonical-message.schema.json`, `AGENT.md`, `src/cli.py`, `src/config.py`, `src/service.py`, `.agents/skills/knowledge-ingestion/SKILL.md`, and `agents/orchestration/src/build_dispatch_plan.py`) rather than knowledge-store retrieval. No material claim in this record depends on knowledge-store content; none is flagged as unavailable or conflicting from that source because none was queried.

## 14. Handoff

This record is a **G1 Intent Gate handoff** for explicit human Product Owner review. It is not an approval, priority decision, scope grant, or risk acceptance. Per this role's authority limits, it does not decide implementation approach, does not resolve OD-1 through OD-6, and does not authorize dispatch of design or build work. Recommended next step once a Product Owner is named: resolve OD-1 and OD-2 (owner identity and the steward-review-before-design split) before any `requirements-agent` decomposition pass begins.
