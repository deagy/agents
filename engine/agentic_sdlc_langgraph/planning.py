"""Build-time lifecycle-gate sequence planning.

`derive_gate_sequence` is a port of `agentic_sdlc.py`'s `choose_workflow`
(~883-900) + `lifecycle_sequence` (~932-947 / 950-959 depending on
version) phrase-matching-and-cumulative-sequencing semantics: match
`task_text` against every route's `phrases`; among the routes that match,
collect every gate id referenced anywhere in any matched route's `gates`
list; the derived sequence is *every* gate from G1 up through the
highest-indexed gate referenced by any matched route (not just the
specifically-referenced gates -- this cumulative "you asked for gate N,
so you get gates 1..N" behavior is load-bearing and intentional, ported
verbatim from the legacy CLI), minus whatever the caller has explicitly
placed in `ignored_gate_ids`. If no route matches at all, the derived
sequence is empty (the legacy CLI's "needs-triage" case -- this module
doesn't reproduce the workflow-naming concept, only the gate-sequence
derivation).

Architectural note -- why this is a *separate, pre-graph* step rather than
graph topology or a runtime conditional:

A compiled LangGraph `StateGraph`'s node and edge topology is fixed the
moment `.compile()` is called; there is no supported way to add or remove
a gate's nodes/edges from an already-compiled graph on a per-invocation
basis. "Which lifecycle gates apply to this task" therefore has to be
resolved *before* `build_graph` is invoked -- it's a build-time decision,
consumed as the `gates` argument to `build_graph`, not something the graph
itself can decide while running.

This is a deliberate and important distinction from reviewer-route
matching (`choose_route` in `contracts.py`, used inside `graph.py`'s
`dispatch_reviewers_{gate_id}` conditional edges), which stays a *runtime*
conditional evaluated fresh against `state["scope"]` on every invocation,
even though the very same compiled graph object is reused across many
different tasks/threads. Reviewer-route matching only changes which
`Send` targets fire within a gate's already-existing reviewer-dispatch
node -- it never adds or removes a gate (a node) from the graph itself, so
it's free to stay dynamic. Gate-sequence derivation, by contrast, decides
whether a gate's nodes exist in the compiled graph *at all*, so it cannot.
"""

from __future__ import annotations

from typing import Any

from .contracts import choose_route


def derive_gate_sequence(
    task_text: str,
    routes: list[dict[str, Any]],
    ignored_gate_ids: list[str],
    all_gates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the cumulative gate-sequence slice of `all_gates` for
    `task_text`, in G1..G10 order, as a list of gate dicts (not just ids)
    so the result can be passed straight to `build_graph`'s `gates` param.

    `all_gates` is expected to already be in ascending lifecycle order
    (i.e. `lifecycle-gates.json`'s `gates` array as-is) -- this function
    does not re-sort it, it only slices a prefix and filters ignores.
    """
    all_gate_ids = [g["id"] for g in all_gates]
    gates_by_id = {g["id"]: g for g in all_gates}

    unknown_ignored = set(ignored_gate_ids) - set(all_gate_ids)
    if unknown_ignored:
        raise ValueError(
            f"ignored_gate_ids contains unknown lifecycle gates: {sorted(unknown_ignored)}"
        )

    matched_routes = choose_route(task_text, routes)
    referenced_gate_ids = [
        gate_id
        for route in matched_routes
        for gate_id in route.get("gates", [])
        if gate_id in gates_by_id
    ]
    if not referenced_gate_ids:
        return []

    highest_index = max(all_gate_ids.index(gid) for gid in referenced_gate_ids)
    cumulative_ids = all_gate_ids[: highest_index + 1]

    ignored = set(ignored_gate_ids)
    return [gates_by_id[gid] for gid in cumulative_ids if gid not in ignored]
