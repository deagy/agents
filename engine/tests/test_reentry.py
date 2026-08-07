"""Tests for `invalidate_gates` / `reenter_gate` (agentic_sdlc_langgraph.reentry).

Ports, in spirit, the legacy CLI test
`test_invalidation_and_reentry_preserve_history_but_clear_stale_bindings`
(plugins/agentic-sdlc/test/test_agentic_sdlc.py ~106-115), which drives
`invalidate` then `reenter` as two separate steps against JSON files and
asserts: `re_entry_history` gets 2 entries (one per call), the reentered
gate's `status` is `"pending"`, and its `human_approvals` is `[]`.

This module goes one step further, per the Phase-1 spec: since this
project has a real execution engine (unlike the legacy CLI, which only
rewrites JSON), `reenter_gate` must make the compiled graph genuinely
re-dispatch the reentered gate's agents and suspend again at its own
`human_approval_{gate_id}` interrupt -- proven here with a real
`graph.invoke(None, config)` call, not just a state-patch assertion.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agentic_sdlc_langgraph.agents import FakeModelClient
from agentic_sdlc_langgraph.contracts import (
    load_agent_catalog,
    load_lifecycle_gates,
    load_mutation_gates,
    load_profile,
)
from agentic_sdlc_langgraph.graph import build_graph
from agentic_sdlc_langgraph.reentry import invalidate_gates, reenter_gate

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "plugins" / "agentic-sdlc" / "contracts"
PROVIDER_DEFAULTS = REPO_ROOT / "providers" / "agentic-sdlc-defaults"

TASK_TEXT = "Define and review a small internal order-processing API architecture and service"

ALL_GATE_IDS = ["G1", "G2", "G3"]


def _make_graph():
    lifecycle_gates = load_lifecycle_gates(CONTRACTS / "lifecycle-gates.json")
    mutation_gates = load_mutation_gates(CONTRACTS / "mutation-gates.json")
    agent_catalog = load_agent_catalog(PROVIDER_DEFAULTS / "agent-catalog.json")
    profile = load_profile(PROVIDER_DEFAULTS / "profiles" / "generic" / "profile.json")
    g1_g3 = [g for g in lifecycle_gates if g["id"] in set(ALL_GATE_IDS)]

    model_client = FakeModelClient()
    checkpointer = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    graph = build_graph(
        gates=g1_g3,
        gate_bindings=profile["gate_bindings"],
        routes=profile["routing"],
        agent_catalog=agent_catalog,
        model_client=model_client,
        checkpointer=checkpointer,
        mutation_gates=mutation_gates,
    )
    return graph


def _initial_state(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "classification": "internal",
        "scope": TASK_TEXT,
        "current_lifecycle_phase": "intent",
        "lifecycle_gates": {},
        "re_entry_history": [],
        "authorities": {
            "product_owner": {"status": "assigned"},
            "engineering_lead": {"status": "assigned"},
            "system_architect": {"status": "assigned"},
        },
        "agent_outputs": {},
        "mutation_gate_pending": None,
        "mutation_gate_decision": None,
        "run_halted": False,
    }


_APPROVAL = {
    "status": "approved",
    "approver": {"id": "product_owner", "role": "Product Owner", "kind": "human"},
    "evidence_refs": [{
        "evidence_id": "test-evidence",
        "uri": "test-evidence:manual",
        "hash_algorithm": "sha256",
        "hash": "0" * 64,
        "classification": "internal",
    }],
}


def test_invalidate_then_reenter_preserve_history_but_clear_stale_bindings_and_reexecute():
    graph = _make_graph()
    config = {"configurable": {"thread_id": "task-reentry-001"}}

    # Drive G1 and G2 to "approved". (G3 ends up dispatched/"ready" too,
    # sitting at its own not-yet-decided human_approval interrupt, since
    # approving G2 lets the graph fall straight through to G3's dispatch
    # in the same invoke call -- there is no "approved-but-stop-before-
    # dispatching-the-next-gate" checkpoint in this graph. This is a fine
    # starting point for exercising invalidate/reenter against a gate
    # (G2) with real, non-placeholder data.)
    result = graph.invoke(_initial_state("task-reentry-001"), config=config)
    assert result["__interrupt__"][0].value["gate_id"] == "G1"

    result = graph.invoke(Command(resume=_APPROVAL), config=config)
    assert result["__interrupt__"][0].value["gate_id"] == "G2"

    result = graph.invoke(Command(resume=_APPROVAL), config=config)
    assert result["__interrupt__"][0].value["gate_id"] == "G3"

    state = graph.get_state(config).values
    assert state["lifecycle_gates"]["G1"]["status"] == "approved"
    assert state["lifecycle_gates"]["G2"]["status"] == "approved"
    assert state["lifecycle_gates"]["G2"]["human_approvals"] != []
    assert state["lifecycle_gates"]["G2"]["artifact_bindings"] != []

    # --- invalidate from G2 forward -------------------------------------
    invalidation_record = invalidate_gates(
        graph,
        config,
        earliest_gate_id="G2",
        reason="requirements changed",
        actor="test-owner",
        all_gate_ids=ALL_GATE_IDS,
    )
    assert invalidation_record["invalidated_gate_ids"] == ["G2", "G3"]

    state = graph.get_state(config).values
    assert len(state["re_entry_history"]) == 1
    assert state["lifecycle_gates"]["G2"]["status"] == "invalidated"
    assert state["lifecycle_gates"]["G2"]["required_reentry_gate"] == "G2"
    # Downstream cascade: G3 (at or after the earliest invalidated gate)
    # must also be invalidated.
    assert state["lifecycle_gates"]["G3"]["status"] == "invalidated"
    # G1 (before the earliest invalidated gate) must be untouched.
    assert state["lifecycle_gates"]["G1"]["status"] == "approved"
    # invalidate() alone must NOT clear stale bindings/approvals yet --
    # they stay as stale-but-visible audit trail until reenter().
    assert state["lifecycle_gates"]["G2"]["human_approvals"] != []
    assert state["lifecycle_gates"]["G2"]["artifact_bindings"] != []
    assert len(state["lifecycle_gates"]["G2"]["invalidation_history"]) == 1

    # --- reenter from G2 forward -----------------------------------------
    reentry_record = reenter_gate(
        graph,
        config,
        earliest_gate_id="G2",
        reason="prepare revised baseline",
        actor="test-owner",
        all_gate_ids=ALL_GATE_IDS,
    )
    assert reentry_record["invalidated_gate_ids"] == []

    state = graph.get_state(config).values
    # Exactly 2 entries: one from invalidate_gates, one from reenter_gate.
    assert len(state["re_entry_history"]) == 2
    assert state["lifecycle_gates"]["G2"]["status"] == "pending"
    assert state["lifecycle_gates"]["G2"]["human_approvals"] == []
    assert state["lifecycle_gates"]["G2"]["artifact_bindings"] == []
    assert state["lifecycle_gates"]["G2"]["evidence_refs"] == []
    assert state["lifecycle_gates"]["G2"]["decided_at"] is None
    assert state["lifecycle_gates"]["G2"]["required_reentry_gate"] is None
    assert state["lifecycle_gates"]["G3"]["status"] == "pending"
    # G1 remains untouched by reenter, same as by invalidate.
    assert state["lifecycle_gates"]["G1"]["status"] == "approved"

    # --- the stronger assertion the legacy CLI could never make: prove
    # real re-execution, not just a flipped status field. Resuming the
    # graph must genuinely re-dispatch G2's author/reviewer agents fresh
    # and suspend again at G2's own human-approval interrupt.
    result = graph.invoke(None, config=config)
    assert "__interrupt__" in result and result["__interrupt__"]
    payload = result["__interrupt__"][0].value
    assert payload["gate_id"] == "G2"
    assert payload["authority_requirements"], "G2 must have non-empty authority_requirements again"

    state = graph.get_state(config).values
    # G2 was genuinely re-run: gate_decision_G2 ran again and produced a
    # fresh "ready" status (not the stale "approved" from before
    # invalidation, and not the "pending" placeholder reenter_gate wrote
    # -- an actual node executed).
    assert state["lifecycle_gates"]["G2"]["status"] == "ready"
    assert state["lifecycle_gates"]["G2"]["preparers"], "G2's author must have been dispatched again"
    # Regression pin: `agent_outputs` is keyed by
    # f"{gate_id}:{kind}:{agent_id}" (`state.merge_agent_outputs`), not an
    # append-only list, precisely so a redispatch after reenter overwrites
    # its own prior slot instead of duplicating alongside the stale
    # pre-invalidation output. G2 has exactly one bound author
    # (requirements-agent, -> 1 preparer) and one reviewer (code-reviewer,
    # via the matched route), each contributing one artifact_binding (one
    # from the author's output, one from the reviewer's) -- if this were
    # still append-only, re-dispatching G2 would leave the old
    # pre-invalidation outputs sitting in the list too, and these counts
    # would be doubled (2 preparers, 4 artifact_bindings).
    assert len(state["lifecycle_gates"]["G2"]["preparers"]) == 1
    assert len(state["lifecycle_gates"]["G2"]["artifact_bindings"]) == 2
    assert state["lifecycle_gates"]["G2"]["independent_verifier"] is not None
    # G1 still untouched throughout.
    assert state["lifecycle_gates"]["G1"]["status"] == "approved"
    assert len(state["lifecycle_gates"]["G1"]["preparers"]) == 1


def test_reenter_gate_resolves_predecessor_via_mutation_gate_check_when_earliest_gate_is_first():
    """When `earliest_gate_id` has no in-sequence predecessor, the patch
    must be written `as_node="mutation_gate_check"` (the graph's entry
    guard) so re-execution starts the whole chain over from G1."""
    graph = _make_graph()
    config = {"configurable": {"thread_id": "task-reentry-002"}}

    result = graph.invoke(_initial_state("task-reentry-002"), config=config)
    assert result["__interrupt__"][0].value["gate_id"] == "G1"

    result = graph.invoke(Command(resume=_APPROVAL), config=config)
    assert result["__interrupt__"][0].value["gate_id"] == "G2"

    invalidate_gates(
        graph, config, earliest_gate_id="G1", reason="major pivot", actor="owner",
        all_gate_ids=ALL_GATE_IDS,
    )
    reenter_gate(
        graph, config, earliest_gate_id="G1", reason="restart", actor="owner",
        all_gate_ids=ALL_GATE_IDS,
    )

    state = graph.get_state(config).values
    assert state["lifecycle_gates"]["G1"]["status"] == "pending"
    assert state["lifecycle_gates"]["G2"]["status"] == "pending"

    result = graph.invoke(None, config=config)
    assert "__interrupt__" in result and result["__interrupt__"]
    assert result["__interrupt__"][0].value["gate_id"] == "G1"
