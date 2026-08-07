"""`invalidate_gates` / `reenter_gate`: live-graph-state ports of the legacy
CLI's `invalidate` (agentic_sdlc.py ~1593-1625) and `reenter`
(~1628-1649) commands.

The legacy commands are pure JSON-file rewrites with no execution engine
behind them -- `invalidate` marks gates `"invalidated"` and records history;
`reenter` resets gate fields to a fresh "pending" shape and records a
second history entry, then returns. Neither one re-runs anything, because
the legacy CLI has nothing to re-run.

This project *does* have a live execution engine (the compiled LangGraph
`StateGraph`), so `reenter_gate` goes one step further than its legacy
counterpart: after writing the reset-gate patch, it redirects the graph's
checkpointed position via `update_state(..., as_node=<predecessor>)` so
that a subsequent `graph.invoke(None, config)` genuinely re-dispatches
`earliest_gate_id`'s author/reviewer agents and suspends again at its own
`human_approval_{earliest_gate_id}` interrupt -- not just a state field
flip.

Both functions preserve the legacy quirk that `invalidate` does NOT clear
`artifact_bindings` / `evidence_refs` / `human_approvals` (those stay
visible as stale-but-audited history at that step); only `reenter` clears
them. See the module-level docstrings of `invalidate_gates` and
`reenter_gate` below for the precise field-by-field behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .export import _base_placeholder_gate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _existing_or_placeholder(gates: dict[str, Any], gate_id: str) -> dict[str, Any]:
    """Return a mutable copy of `gates[gate_id]`, or a fresh schema-shaped
    placeholder if the gate was never reached by the graph (e.g. an
    in-sequence gate that hasn't been dispatched yet -- `lifecycle_gates`
    only gets a real entry once `gate_decision_{gate_id}` has run at least
    once). Reuses `export._base_placeholder_gate` so the placeholder shape
    always matches what `export_run_record` would synthesize for the same
    not-yet-reached gate.
    """
    if gate_id in gates:
        return dict(gates[gate_id])
    return _base_placeholder_gate(gate_id)


def invalidate_gates(
    graph: Any,
    config: dict[str, Any],
    earliest_gate_id: str,
    reason: str,
    actor: str,
    all_gate_ids: list[str],
) -> dict[str, Any]:
    """Port of the legacy `invalidate` command.

    For `earliest_gate_id` and every gate at or after it in
    `all_gate_ids` order: set `status = "invalidated"` and
    `required_reentry_gate = earliest_gate_id`. Deliberately does NOT
    clear `artifact_bindings` / `evidence_refs` / `human_approvals` --
    those stay as stale-but-visible audit trail until `reenter_gate`
    clears them (mirrors the legacy CLI's `invalidate`, which never
    touches those fields either).

    Collects every affected gate's `artifact_bindings` into one
    `Invalidation` record (`affected_artifact_bindings`), appends that
    record to the top-level `re_entry_history` and to each affected
    gate's own `invalidation_history`, and writes the patch via a plain
    `graph.update_state(config, patch)` -- no `as_node` is needed since
    this step only records state, it never needs to resume execution
    (mirrors the legacy CLI's `invalidate`, which just rewrites JSON and
    returns without re-running anything).

    Returns the `Invalidation` record that was appended.
    """
    snapshot = graph.get_state(config)
    current_gates: dict[str, Any] = snapshot.values.get("lifecycle_gates", {})
    start = all_gate_ids.index(earliest_gate_id)
    invalidated_ids = all_gate_ids[start:]

    affected_bindings: list[dict[str, Any]] = []
    for gid in invalidated_ids:
        gate = current_gates.get(gid)
        if gate:
            affected_bindings.extend(gate.get("artifact_bindings", []))

    record = {
        "invalidated_at": _now(),
        "actor": actor,
        "reason": reason,
        "earliest_gate": earliest_gate_id,
        "invalidated_gate_ids": invalidated_ids,
        "affected_artifact_bindings": affected_bindings,
        "superseding_artifact_id": None,
    }

    gate_patch: dict[str, Any] = {}
    for gid in invalidated_ids:
        gate = _existing_or_placeholder(current_gates, gid)
        gate["status"] = "invalidated"
        gate["required_reentry_gate"] = earliest_gate_id
        gate["invalidation_history"] = list(gate.get("invalidation_history", [])) + [record]
        gate_patch[gid] = gate

    graph.update_state(config, {"lifecycle_gates": gate_patch, "re_entry_history": [record]})
    return record


def _predecessor_node(graph: Any, earliest_gate_id: str, all_gate_ids: list[str]) -> str:
    """Resolve whatever node in the compiled graph has an outgoing edge
    into `earliest_gate_id`'s `dispatch_authors_{earliest_gate_id}` node.

    For the linear prerequisite chains this project builds (each gate's
    only in-sequence prerequisite is its immediate predecessor in
    `all_gate_ids`), that's the immediately-preceding gate's exit node --
    `human_approval_{prereq}` if that gate has one (every gate with
    authority_requirements or `human_only` does), else
    `gate_decision_{prereq}`. If `earliest_gate_id` has no in-sequence
    predecessor at all (it's first in `all_gate_ids`), the predecessor
    node is the graph's own entry guard, `mutation_gate_check`.

    Introspects the compiled graph's actual node set (`graph.nodes`)
    rather than requiring the raw gate contracts here, so this stays
    correct even if a gate's exit-node shape ever changes.
    """
    start = all_gate_ids.index(earliest_gate_id)
    if start == 0:
        return "mutation_gate_check"
    prereq = all_gate_ids[start - 1]
    if f"human_approval_{prereq}" in graph.nodes:
        return f"human_approval_{prereq}"
    if f"gate_decision_{prereq}" in graph.nodes:
        return f"gate_decision_{prereq}"
    return "mutation_gate_check"


def reenter_gate(
    graph: Any,
    config: dict[str, Any],
    earliest_gate_id: str,
    reason: str,
    actor: str,
    all_gate_ids: list[str],
) -> dict[str, Any]:
    """Port of the legacy `reenter` command, extended to actually make the
    graph re-execute (the legacy CLI has no execution engine of its own,
    only bookkeeping -- see module docstring).

    For `earliest_gate_id` and every gate at or after it: reset
    `status = "pending"`, `required_reentry_gate = None`, and clear
    `artifact_bindings` / `evidence_refs` / `human_approvals` /
    `decided_at`. Appends a second `Invalidation` record to
    `re_entry_history` with `invalidated_gate_ids: []` (matching the
    legacy CLI's `reenter`, which appends its own history entry marking
    that gates are being reset, not newly invalidated).

    Then writes that patch via `graph.update_state(config, patch,
    as_node=<predecessor node>)`, so the checkpoint records the patch as
    though it came from whatever node feeds `earliest_gate_id`'s dispatch
    -- this is what makes a subsequent `graph.invoke(None, config)`
    genuinely re-dispatch `earliest_gate_id`'s author/reviewer agents and
    suspend again at its own `human_approval_{earliest_gate_id}`
    interrupt, rather than just leaving a flipped status field sitting
    inert in the checkpoint.

    Returns the `Invalidation` record that was appended. Caller is
    responsible for actually resuming execution (`graph.invoke(None,
    config)`) if desired.
    """
    snapshot = graph.get_state(config)
    current_gates: dict[str, Any] = snapshot.values.get("lifecycle_gates", {})
    start = all_gate_ids.index(earliest_gate_id)
    reentered_ids = all_gate_ids[start:]

    record = {
        "invalidated_at": _now(),
        "actor": actor,
        "reason": reason,
        "earliest_gate": earliest_gate_id,
        "invalidated_gate_ids": [],
        "affected_artifact_bindings": [],
        "superseding_artifact_id": None,
    }

    gate_patch: dict[str, Any] = {}
    for gid in reentered_ids:
        gate = _existing_or_placeholder(current_gates, gid)
        gate["status"] = "pending"
        gate["required_reentry_gate"] = None
        gate["artifact_bindings"] = []
        gate["evidence_refs"] = []
        gate["human_approvals"] = []
        gate["decided_at"] = None
        gate_patch[gid] = gate

    predecessor_node = _predecessor_node(graph, earliest_gate_id, all_gate_ids)

    graph.update_state(
        config,
        {"lifecycle_gates": gate_patch, "re_entry_history": [record]},
        as_node=predecessor_node,
    )
    return record
