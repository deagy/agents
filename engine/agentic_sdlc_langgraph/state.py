"""LangGraph state model for the Phase-0 Agentic SDLC spike.

`GateState` is a field-for-field port of `run-record.schema.json`'s `gate`
`$def`. `SDLCState` is the graph-level state; the checkpointed value of this
state *is* the run record for a given `task_id` (one thread per task).

Deliberate simplifications for this spike (see the phase-0 report for the
full list):

- No `provider_bindings` / `dispatch_binding_digest` / `contract_digest` /
  `knowledge_retrieval` / `impact_profile` modeling in the live graph state
  — those are synthesized as schema-satisfying placeholders only at export
  time (`export.py`), not carried through the graph.
- `mode`, `baseline_revision`, `disposition` (top-level run-record fields)
  are likewise handled only at export time, not modeled as live graph
  state, since nothing in the G1-G3 slice computes them.
- `intent_record_id` / `requirements_baseline_id` ARE modeled as live state
  (see below) -- they're set once, optionally, at `plan` time from a
  `--intent-gitlab-issue`/`--requirements-gitlab-issue` argument (see
  `gitlab_issue.py`, `cli.py`'s `plan`), then read back unchanged at export
  time. No node ever recomputes them after planning; unlike the
  `Annotated[..., reducer]` fields below, a plain field here is correct
  because nothing but the initial state ever sets it.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class Identity(TypedDict):
    id: str
    role: str
    kind: str  # "human" | "agent" | "service"


class ArtifactBinding(TypedDict):
    artifact_id: str
    revision: str
    digest: str


class Evidence(TypedDict):
    evidence_id: str
    uri: str
    hash_algorithm: str
    hash: str
    classification: str


class AuthorityRequirement(TypedDict):
    authority_id: str
    authority_type: str  # always "human-approver" in this contract
    role: str
    applicability: str  # "applicable" | "not-applicable" | "unknown"
    rationale: str | None


class Approval(TypedDict):
    status: str  # "pending" | "approved" | "rejected" | "not-required"
    approver: Identity | None
    decided_at: str | None
    evidence_refs: list[Evidence]


class IndependenceDeclaration(TypedDict):
    verifier_confirmed_not_preparer: bool
    verifier_made_material_correction: bool  # schema pins this to `false`


class Finding(TypedDict):
    finding_id: str
    severity: str
    status: str
    owner: str


class Exception_(TypedDict):
    exception_id: str
    finding_id: str
    justification: str
    compensating_controls: list[str]
    owner: Identity
    approver: Identity
    expires_at: str
    remediation_plan: str


class Invalidation(TypedDict):
    invalidated_at: str
    actor: str
    reason: str
    earliest_gate: str
    invalidated_gate_ids: list[str]
    affected_artifact_bindings: list[ArtifactBinding]
    superseding_artifact_id: str | None


class GateState(TypedDict):
    tier: str  # "lifecycle" | "specialist"
    gate_id: str
    name: str
    applicability: str  # "applicable" | "not-applicable" | "unknown"
    applicability_rationale: str | None
    status: str  # pending|ready|approved|request-changes|needs-information|blocked|invalidated
    artifact_bindings: list[ArtifactBinding]
    preparers: list[Identity]
    independent_verifier: Identity | None
    independence_declaration: IndependenceDeclaration
    authority_requirements: list[AuthorityRequirement]
    human_approvals: list[Approval]
    decided_at: str | None
    evidence_refs: list[Evidence]
    knowledge_status: str
    findings: list[Finding]
    exceptions: list[Exception_]
    invalidation_history: list[Invalidation]
    required_reentry_gate: str | None


def merge_gate_updates(
    current: dict[str, GateState] | None, update: dict[str, GateState] | None
) -> dict[str, GateState]:
    """Per-gate-id dict merge reducer.

    Parallel `Send` branches (and sequential nodes) touching different gate
    ids must not clobber each other's entries. Each key in `update` fully
    replaces the corresponding key in `current` (nodes are expected to read
    the current gate dict and return a complete replacement for that gate
    id, not a sparse patch) while every other gate id in `current` is left
    untouched.
    """
    current = dict(current or {})
    update = update or {}
    current.update(update)
    return current


def merge_agent_outputs(
    current: dict[str, dict[str, Any]] | None, update: dict[str, dict[str, Any]] | None
) -> dict[str, dict[str, Any]]:
    """Per-dispatch-slot dict merge reducer for `agent_outputs`.

    Keyed by `f"{gate_id}:{kind}:{agent_id}"` (one slot per agent per role
    per gate), with the same later-write-wins semantics as
    `merge_gate_updates`. This fixes a real duplication bug: with a plain
    `operator.add` (append-only) list reducer, re-dispatching a gate's
    agents after `reenter_gate` would leave the gate's stale
    pre-invalidation outputs sitting in the list alongside the fresh ones
    -- `gate_decision_{gate_id}` filters only by `gate_id`, so it would
    pick up both, duplicating `preparers`/`artifact_bindings`/
    `evidence_refs`. Keying by dispatch slot means a redispatch of the
    same agent/role/gate simply overwrites its own prior entry instead of
    appending a duplicate, while parallel `Send` branches for *different*
    agents within the same gate still get distinct keys and never clobber
    each other.
    """
    current = dict(current or {})
    update = update or {}
    current.update(update)
    return current


class SDLCState(TypedDict):
    task_id: str
    classification: str
    scope: str  # the task text; also what routing/mutation-gate matching reads
    current_lifecycle_phase: str

    # optional, set once at plan time from --intent-gitlab-issue /
    # --requirements-gitlab-issue (see gitlab_issue.py); None if not supplied.
    # Never approval evidence -- gate approval status is unaffected by these.
    intent_record_id: str | None
    requirements_baseline_id: str | None

    lifecycle_gates: Annotated[dict[str, GateState], merge_gate_updates]

    re_entry_history: Annotated[list[Invalidation], operator.add]

    # authority-assignment map fed in at invoke time, e.g.
    # {"product_owner": {"status": "assigned"}, ...}. Not part of the
    # exported run-record schema; mirrors the project `authorities.json`
    # overlay file from the legacy CLI.
    authorities: dict[str, dict[str, Any]]

    # map-reduce fan-in scratch field, keyed by `f"{gate_id}:{kind}:{agent_id}"`
    # (see `merge_agent_outputs`): every dispatched agent node writes one
    # AgentOutput-shaped dict to its own slot here. Consumed by
    # gate_decision_{gate_id} nodes and filtered by `gate_id`; never
    # exported.
    agent_outputs: Annotated[dict[str, dict[str, Any]], merge_agent_outputs]

    # populated by the mutation-gate guard at graph entry; independent of
    # gate/authority approval status. Non-None whenever a human-only
    # mutation phrase matched `scope` (regardless of whether it was
    # subsequently authorized) -- see graph.py's `mutation_gate_check`.
    mutation_gate_pending: dict[str, Any] | None

    # the human's authorization decision for `mutation_gate_pending`, once
    # made (None if no mutation gate matched, or a match hasn't been
    # resolved yet -- though in practice `mutation_gate_check` always
    # resolves this via `interrupt()` in the same node invocation that
    # sets `mutation_gate_pending`).
    mutation_gate_decision: dict[str, Any] | None

    # top-level hard-stop indicator: True iff a mutation-gate phrase
    # matched and the human explicitly rejected (or never authorized)
    # proceeding. While True, no gate dispatch node ever runs -- the graph
    # routes straight to END from `mutation_gate_check`. This is
    # independent of, and precedes, any per-gate human-approval interrupt.
    run_halted: bool
