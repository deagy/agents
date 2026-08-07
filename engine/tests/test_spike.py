"""Phase-0 spike smoke test.

Proves, against the *real* contract/profile/catalog files (no mocks of
those), that:

- `build_graph` (generic, not hardcoded to G1/G2/G3 by name) wires the
  G1-G3 slice of `lifecycle-gates.json` correctly.
- The compiled graph suspends via `interrupt()` at G1's, G2's, and G3's
  human-approval nodes (all three -- not just G2 -- since every gate in
  this contract's `authority_requirements` is typed `human-approver`).
- Resuming with `Command(resume=...)` carries the run forward gate by
  gate to a terminal "all three approved" state.
- `export_run_record` produces a dict that validates against the real
  `run-record.schema.json` with `jsonschema.Draft202012Validator`.
- Separation-of-duties enforcement blocks a gate when the reviewer and an
  author resolve to the same agent id.

Uses `FakeModelClient` throughout -- no ANTHROPIC_API_KEY is configured in
this environment and none of this should hit the network.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import jsonschema
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agentic_sdlc_langgraph.agents import FakeModelClient
from agentic_sdlc_langgraph.contracts import (
    load_agent_catalog,
    load_lifecycle_gates,
    load_mutation_gates,
    load_profile,
    mutation_gate_guard,
)
from agentic_sdlc_langgraph.export import export_run_record
from agentic_sdlc_langgraph.graph import build_graph
from agentic_sdlc_langgraph.planning import derive_gate_sequence
from agentic_sdlc_langgraph.validate import validate_run_record

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "plugins" / "agentic-sdlc" / "contracts"
PROVIDER_DEFAULTS = REPO_ROOT / "providers" / "agentic-sdlc-defaults"


@pytest.fixture()
def contracts():
    lifecycle_gates = load_lifecycle_gates(CONTRACTS / "lifecycle-gates.json")
    mutation_gates = load_mutation_gates(CONTRACTS / "mutation-gates.json")
    agent_catalog = load_agent_catalog(PROVIDER_DEFAULTS / "agent-catalog.json")
    profile = load_profile(PROVIDER_DEFAULTS / "profiles" / "generic" / "profile.json")
    g1_g3 = [g for g in lifecycle_gates if g["id"] in {"G1", "G2", "G3"}]
    return {
        "lifecycle_gates_full": lifecycle_gates,
        "g1_g3": g1_g3,
        "mutation_gates": mutation_gates,
        "agent_catalog": agent_catalog,
        "profile": profile,
    }


def _make_graph(contracts, model_client=None):
    model_client = model_client or FakeModelClient()
    checkpointer = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    graph = build_graph(
        gates=contracts["g1_g3"],
        gate_bindings=contracts["profile"]["gate_bindings"],
        routes=contracts["profile"]["routing"],
        agent_catalog=contracts["agent_catalog"],
        model_client=model_client,
        checkpointer=checkpointer,
        mutation_gates=contracts["mutation_gates"],
    )
    return graph


TASK_TEXT = "Define and review a small internal order-processing API architecture and service"


def test_g1_g3_interrupt_resume_and_export(contracts):
    graph = _make_graph(contracts)
    config = {"configurable": {"thread_id": "task-001"}}

    initial_state = {
        "task_id": "task-001",
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

    result = graph.invoke(initial_state, config=config)

    # --- suspended at G1's human approval ---
    assert "__interrupt__" in result
    interrupts = result["__interrupt__"]
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert payload["gate_id"] == "G1"
    assert payload["authority_requirements"], "G1 must have non-empty authority_requirements"

    state_snapshot = graph.get_state(config)
    assert state_snapshot.values["lifecycle_gates"]["G1"]["status"] == "ready"
    assert state_snapshot.values["mutation_gate_pending"] is None  # task text matches no mutation phrase
    assert state_snapshot.values["run_halted"] is False

    # --- resume G1 with approval ---
    approval = {
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
    result = graph.invoke(Command(resume=approval), config=config)
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["gate_id"] == "G2"

    state_snapshot = graph.get_state(config)
    assert state_snapshot.values["lifecycle_gates"]["G1"]["status"] == "approved"
    g1_preparers = state_snapshot.values["lifecycle_gates"]["G1"]["preparers"]
    assert [p["id"] for p in g1_preparers] == ["product-intent-agent"]
    assert state_snapshot.values["lifecycle_gates"]["G1"]["independent_verifier"]["id"] == "code-reviewer"

    # --- resume G2 with approval ---
    result = graph.invoke(Command(resume=approval), config=config)
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["gate_id"] == "G3"

    state_snapshot = graph.get_state(config)
    assert state_snapshot.values["lifecycle_gates"]["G2"]["status"] == "approved"

    # --- resume G3 with approval -> terminal ---
    result = graph.invoke(Command(resume=approval), config=config)
    assert "__interrupt__" not in result or not result["__interrupt__"]

    final_state = graph.get_state(config).values
    for gate_id in ("G1", "G2", "G3"):
        assert final_state["lifecycle_gates"][gate_id]["status"] == "approved"

    # --- export + validate against the real schema ---
    # This test only ever built a G1-G3 slice (not a `derive_gate_sequence`
    # result), so G4-G10 are correctly "not-applicable" here, not
    # "pending" -- they were never part of this run's derived sequence at
    # all. Pass that explicitly rather than relying on the "assume
    # everything is in scope" default.
    record = export_run_record(final_state, sequence_gate_ids=["G1", "G2", "G3"])
    schema = __import__("json").loads(
        (CONTRACTS / "run-record.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(record))
    assert errors == [], f"schema validation errors: {errors}"
    assert len(record["lifecycle_gates"]) == 10
    assert [g["gate_id"] for g in record["lifecycle_gates"]] == [f"G{n}" for n in range(1, 11)]
    for gate_id in ("G4", "G5", "G6", "G7", "G8", "G9", "G10"):
        gate = next(g for g in record["lifecycle_gates"] if g["gate_id"] == gate_id)
        assert gate["applicability"] == "not-applicable"


def test_mutation_gate_guard_fires_on_production_deploy_phrase(contracts):
    result = mutation_gate_guard(
        "deploy to production tonight", contracts["mutation_gates"]
    )
    assert result is not None
    assert result["matched"][0]["id"] == "production-deployment"


def test_mutation_gate_guard_does_not_fire_on_ordinary_task(contracts):
    result = mutation_gate_guard(TASK_TEXT, contracts["mutation_gates"])
    assert result is None


def test_separation_of_duties_blocks_gate_when_reviewer_equals_author(contracts):
    """Construct the gate_decision logic's core invariant directly: if the
    independent verifier's id matches a preparer id, status must be
    "blocked", never "approved". We exercise this via a real graph run
    where FakeModelClient is configured so the *same* agent id is
    dispatched as both author and reviewer for G1 -- achieved by pointing
    a synthetic profile's G1 contribution and route reviewers at the same
    agent id.
    """
    gates = [g for g in contracts["lifecycle_gates_full"] if g["id"] == "G1"]
    gate_bindings = {
        "G1": {
            "contributions": {
                "intent": {
                    "agents": ["product-intent-agent"],
                    "tasks": ["capture-intent"],
                    "artifacts": ["intent-record"],
                }
            }
        }
    }
    # Route reviewers deliberately reuse the same author agent id so the
    # independent verifier collides with a preparer.
    routes = [
        {
            "id": "colliding-route",
            "phrases": ["architecture"],
            "agents": [],
            "reviewers": ["product-intent-agent"],
            "support": [],
            "gates": ["G1"],
        }
    ]
    agent_catalog = dict(contracts["agent_catalog"])
    # product-intent-agent is "author" kind in the real catalog; the route
    # dispatches it as a reviewer regardless of catalog kind (route
    # reviewers are taken at face value per spec, not filtered by catalog
    # kind) -- this is exactly the collision scenario.

    model_client = FakeModelClient()
    checkpointer = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    graph = build_graph(
        gates=gates,
        gate_bindings=gate_bindings,
        routes=routes,
        agent_catalog=agent_catalog,
        model_client=model_client,
        checkpointer=checkpointer,
        mutation_gates=[],
    )
    config = {"configurable": {"thread_id": "task-collision"}}
    initial_state = {
        "task_id": "task-collision",
        "classification": "internal",
        "scope": "architecture review task",
        "current_lifecycle_phase": "intent",
        "lifecycle_gates": {},
        "re_entry_history": [],
        "authorities": {"product_owner": {"status": "assigned"}},
        "agent_outputs": {},
        "mutation_gate_pending": None,
        "mutation_gate_decision": None,
        "run_halted": False,
    }
    result = graph.invoke(initial_state, config=config)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert "violation" in payload["reason"].lower() or "cannot approve" in payload["reason"].lower()

    state_snapshot = graph.get_state(config)
    assert state_snapshot.values["lifecycle_gates"]["G1"]["status"] == "blocked"

    # Even resuming with an "approved" decision must not flip it to approved.
    result = graph.invoke(
        Command(resume={"status": "approved", "approver": None, "evidence_refs": []}),
        config=config,
    )
    final = graph.get_state(config).values
    assert final["lifecycle_gates"]["G1"]["status"] == "blocked"
    assert final["lifecycle_gates"]["G1"]["human_approvals"][0]["status"] == "rejected"

    # The blocked-gate record must still be schema-valid (this is what
    # caught a real bug during development: "blocked" is a valid
    # gate.status value but NOT a valid approval.status value -- they are
    # two different enums in run-record.schema.json).
    record = export_run_record(final, sequence_gate_ids=["G1"])
    schema = __import__("json").loads(
        (CONTRACTS / "run-record.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(record))
    assert errors == [], f"schema validation errors: {errors}"


# --------------------------------------------------------------------------
# Phase 1: derive_gate_sequence -- pre-graph gate-sequence planning
# --------------------------------------------------------------------------


def test_derive_gate_sequence_cumulative_logic_is_independent_of_shipped_profile(contracts):
    """Prove the cumulative "matched gate N pulls in G1..GN" behavior with
    directly-constructed routes, independent of the shipped generic
    profile's real routing content (which only ever reaches G3)."""
    all_gates = contracts["lifecycle_gates_full"]
    routes = [
        {"id": "r1", "phrases": ["alpha"], "gates": ["G2"]},
        {"id": "r2", "phrases": ["bravo"], "gates": ["G7"]},
    ]

    # Only "alpha" matches -> highest referenced gate is G2 -> G1..G2.
    sequence = derive_gate_sequence("an alpha task", routes, [], all_gates)
    assert [g["id"] for g in sequence] == ["G1", "G2"]

    # Both match -> highest referenced gate is G7 -> cumulative G1..G7,
    # even though neither route directly references G1, G3, G4, G5, or G6.
    sequence = derive_gate_sequence("an alpha and bravo task", routes, [], all_gates)
    assert [g["id"] for g in sequence] == [f"G{n}" for n in range(1, 8)]

    # Nothing matches -> empty sequence (the "needs-triage" case).
    sequence = derive_gate_sequence("no matching phrase whatsoever", routes, [], all_gates)
    assert sequence == []


def test_derive_gate_sequence_excludes_ignored_gates(contracts):
    all_gates = contracts["lifecycle_gates_full"]
    routes = [{"id": "r", "phrases": ["charlie"], "gates": ["G6"]}]

    sequence = derive_gate_sequence("a charlie task", routes, ["G3", "G5"], all_gates)
    assert [g["id"] for g in sequence] == ["G1", "G2", "G4", "G6"]


def test_derive_gate_sequence_rejects_unknown_ignored_gate_ids(contracts):
    all_gates = contracts["lifecycle_gates_full"]
    with pytest.raises(ValueError):
        derive_gate_sequence("anything", [], ["G99"], all_gates)


# --------------------------------------------------------------------------
# Phase 1: full G1-G10 happy path
# --------------------------------------------------------------------------

FULL_CHAIN_TASK_TEXT = (
    "Define the architecture and service scope, then advance through every "
    "phase up to the final release milestone."
)


def _full_chain_routes(profile):
    # The shipped generic profile's one route only reaches G3. Add a
    # synthetic route whose matched phrase references G10 so
    # `derive_gate_sequence`'s cumulative logic pulls in the full G1-G10
    # chain, per the task spec ("you just need any matched route
    # referencing a gate as high as G10"). The real "new-service" route
    # is kept in the mix so G1-G3 keep their real `code-reviewer`
    # dynamic-reviewer behavior, exactly as in the G1-G3 spike test.
    return profile["routing"] + [
        {
            "id": "full-chain-test",
            "phrases": ["final release milestone"],
            "agents": [],
            "reviewers": [],
            "support": [],
            "gates": ["G10"],
        }
    ]


def _full_chain_authorities():
    authority_ids = [
        "product_owner",
        "engineering_lead",
        "system_architect",
        "governance_lead",
        "data_control_owner",
        "security_lead",
        "human_key_owner",
        "uat_product_owner",
        "release_owner",
        "release_authority",
        "service_owner",
        "implicated_security_lead",
        "implicated_governance_lead",
    ]
    return {authority_id: {"status": "assigned"} for authority_id in authority_ids}


def test_full_g1_g10_happy_path_interrupts_in_order_and_exports_clean(contracts):
    lifecycle_gates_full = contracts["lifecycle_gates_full"]
    routes = _full_chain_routes(contracts["profile"])

    # This is the build-time planning step: resolve which gates apply
    # *before* build_graph compiles the topology.
    sequence = derive_gate_sequence(FULL_CHAIN_TASK_TEXT, routes, [], lifecycle_gates_full)
    assert [g["id"] for g in sequence] == [f"G{n}" for n in range(1, 11)]

    model_client = FakeModelClient()
    checkpointer = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    graph = build_graph(
        gates=sequence,
        gate_bindings=contracts["profile"]["gate_bindings"],
        routes=routes,
        agent_catalog=contracts["agent_catalog"],
        model_client=model_client,
        checkpointer=checkpointer,
        mutation_gates=contracts["mutation_gates"],
    )

    config = {"configurable": {"thread_id": "task-full-chain"}}
    initial_state = {
        "task_id": "task-full-chain",
        "classification": "internal",
        "scope": FULL_CHAIN_TASK_TEXT,
        "current_lifecycle_phase": "intent",
        "lifecycle_gates": {},
        "re_entry_history": [],
        "authorities": _full_chain_authorities(),
        "agent_outputs": {},
        "mutation_gate_pending": None,
        "mutation_gate_decision": None,
        "run_halted": False,
    }
    approval = {
        "status": "approved",
        "approver": {"id": "approver", "role": "Approver", "kind": "human"},
        "evidence_refs": [{
            "evidence_id": "test-evidence",
            "uri": "test-evidence:manual",
            "hash_algorithm": "sha256",
            "hash": "0" * 64,
            "classification": "internal",
        }],
    }

    expected_gate_order = [f"G{n}" for n in range(1, 11)]
    seen_gate_order = []

    result = graph.invoke(initial_state, config=config)
    assert "__interrupt__" in result
    seen_gate_order.append(result["__interrupt__"][0].value["gate_id"])

    for _ in range(len(expected_gate_order) - 1):
        result = graph.invoke(Command(resume=approval), config=config)
        assert "__interrupt__" in result and result["__interrupt__"], "expected another gate interrupt"
        seen_gate_order.append(result["__interrupt__"][0].value["gate_id"])

    assert seen_gate_order == expected_gate_order

    # One more resume (approving G10) reaches a terminal state.
    result = graph.invoke(Command(resume=approval), config=config)
    assert "__interrupt__" not in result or not result["__interrupt__"]

    final_state = graph.get_state(config).values
    for gate_id in expected_gate_order:
        assert final_state["lifecycle_gates"][gate_id]["status"] == "approved"

    # G8 has no reviewer-kind agent bound in the generic profile's
    # gate_bindings -- independent_verifier must be structurally None,
    # never fabricated, and this must not block approval.
    assert final_state["lifecycle_gates"]["G8"]["independent_verifier"] is None

    # G9 is `human_only` with zero bound agents at all (no author, no
    # reviewer) -- it must still flow through dispatch/decision/approval
    # cleanly with no preparers and no independent verifier.
    assert final_state["lifecycle_gates"]["G9"]["preparers"] == []
    assert final_state["lifecycle_gates"]["G9"]["independent_verifier"] is None

    record = export_run_record(final_state)
    schema = __import__("json").loads(
        (CONTRACTS / "run-record.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(record))
    assert errors == [], f"schema validation errors: {errors}"
    assert [g["gate_id"] for g in record["lifecycle_gates"]] == expected_gate_order
    for gate in record["lifecycle_gates"]:
        assert gate["status"] == "approved"
        assert gate["applicability"] == "applicable"
    assert record["current_lifecycle_phase"] == "feedback"

    # Regression pin: validate_run_record must accept this exact
    # legitimately-approved full-chain record (G8 has no reviewer bound,
    # G9 is human_only with zero agents at all) as code 0/no errors. An
    # earlier draft of validate_run_record required every approved gate
    # to carry a non-null independent_verifier and non-empty
    # evidence_refs/artifact_bindings unconditionally, which rejected
    # this exact real, valid record -- see validate.py's docstring.
    gate_contracts = {g["id"]: g for g in lifecycle_gates_full}
    code, messages = validate_run_record(record, schema, gate_contracts=gate_contracts)
    assert (code, messages) == (0, []), f"validate_run_record rejected a legitimate full-chain record: {messages}"


# --------------------------------------------------------------------------
# Phase 1: mutation-gate hard interrupt (independent of, and prior to, any
# per-gate human-approval interrupt)
# --------------------------------------------------------------------------

MUTATION_TASK_TEXT = "Please deploy to production for the customer this evening"


def _make_mutation_graph(contracts, gate_ids=("G1", "G2", "G3")):
    gates = [g for g in contracts["lifecycle_gates_full"] if g["id"] in set(gate_ids)]
    model_client = FakeModelClient()
    checkpointer = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    return build_graph(
        gates=gates,
        gate_bindings=contracts["profile"]["gate_bindings"],
        routes=contracts["profile"]["routing"],
        agent_catalog=contracts["agent_catalog"],
        model_client=model_client,
        checkpointer=checkpointer,
        mutation_gates=contracts["mutation_gates"],
    )


def _mutation_initial_state(task_id, scope):
    return {
        "task_id": task_id,
        "classification": "internal",
        "scope": scope,
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


def test_mutation_gate_hard_interrupt_blocks_dispatch_until_authorized(contracts):
    graph = _make_mutation_graph(contracts)
    config = {"configurable": {"thread_id": "task-mutation-auth"}}
    initial_state = _mutation_initial_state("task-mutation-auth", MUTATION_TASK_TEXT)

    result = graph.invoke(initial_state, config=config)

    # (a) interrupts at entry, before any gate's author is dispatched.
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "mutation_gate"
    assert payload["matched"][0]["id"] == "production-deployment"

    state_snapshot = graph.get_state(config)
    assert state_snapshot.values["lifecycle_gates"] == {}
    assert state_snapshot.values["agent_outputs"] == {}

    # (b) authorizing lets the run proceed normally into G1's dispatch.
    result = graph.invoke(
        Command(
            resume={
                "authorized": True,
                "approver": {
                    "id": "release_authority",
                    "role": "Release Authority",
                    "kind": "human",
                },
                "reason": "Reviewed and approved for production deployment",
            }
        ),
        config=config,
    )
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["gate_id"] == "G1"

    state_snapshot = graph.get_state(config)
    assert state_snapshot.values["run_halted"] is False
    assert state_snapshot.values["mutation_gate_decision"]["authorized"] is True
    assert state_snapshot.values["lifecycle_gates"]["G1"]["status"] == "ready"
    assert state_snapshot.values["agent_outputs"], "G1's author should have been dispatched"


def test_mutation_gate_hard_interrupt_halts_run_when_rejected(contracts):
    graph = _make_mutation_graph(contracts)
    config = {"configurable": {"thread_id": "task-mutation-reject"}}
    initial_state = _mutation_initial_state("task-mutation-reject", MUTATION_TASK_TEXT)

    result = graph.invoke(initial_state, config=config)
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["kind"] == "mutation_gate"

    result = graph.invoke(
        Command(
            resume={"authorized": False, "approver": None, "reason": "Not authorized tonight"}
        ),
        config=config,
    )
    # No further interrupt -- the run halts outright, it never falls
    # through to any gate's human-approval interrupt.
    assert "__interrupt__" not in result or not result["__interrupt__"]

    final_state = graph.get_state(config).values
    assert final_state["run_halted"] is True
    assert final_state["mutation_gate_decision"]["authorized"] is False
    # No gate was ever dispatched -- every included gate stays absent
    # from lifecycle_gates (structurally "pending" once exported).
    assert final_state["lifecycle_gates"] == {}
    assert final_state["agent_outputs"] == {}

    record = export_run_record(final_state, sequence_gate_ids=["G1", "G2", "G3"])
    schema = __import__("json").loads(
        (CONTRACTS / "run-record.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(record))
    assert errors == [], f"schema validation errors: {errors}"
    for gate_id in ("G1", "G2", "G3"):
        gate = next(g for g in record["lifecycle_gates"] if g["gate_id"] == gate_id)
        assert gate["status"] == "pending"
        assert gate["applicability"] == "applicable"


def test_build_graph_topology_unaffected_by_classification_payload_addition(contracts):
    """Regression pin: `dispatch_authors_{gate}`/`dispatch_reviewers_{gate}`
    now also pass a `classification` key in each `Send` payload, but that
    is a payload-content-only change -- node/edge topology (names, count,
    conditional-ness) must stay exactly what it was before that change."""
    graph = _make_graph(contracts)
    drawable = graph.get_graph()

    expected_nodes = {
        "__start__",
        "__end__",
        "mutation_gate_check",
        "dispatch_authors_G1",
        "dispatch_reviewers_G1",
        "G1_author_product-intent-agent",
        "G1_reviewer_code-reviewer",
        "gate_decision_G1",
        "human_approval_G1",
        "dispatch_authors_G2",
        "dispatch_reviewers_G2",
        "G2_author_requirements-agent",
        "G2_reviewer_code-reviewer",
        "gate_decision_G2",
        "human_approval_G2",
        "dispatch_authors_G3",
        "dispatch_reviewers_G3",
        "G3_author_cloud-architect",
        "G3_reviewer_code-reviewer",
        "gate_decision_G3",
        "human_approval_G3",
    }
    assert set(drawable.nodes.keys()) == expected_nodes

    edges = {(edge.source, edge.target, edge.conditional) for edge in drawable.edges}
    expected_edges = {
        ("__start__", "mutation_gate_check", False),
        ("mutation_gate_check", "__end__", True),
        ("mutation_gate_check", "dispatch_authors_G1", True),
        ("dispatch_authors_G1", "G1_author_product-intent-agent", True),
        ("dispatch_authors_G1", "dispatch_reviewers_G1", True),
        ("G1_author_product-intent-agent", "dispatch_reviewers_G1", False),
        ("dispatch_reviewers_G1", "G1_reviewer_code-reviewer", True),
        ("dispatch_reviewers_G1", "gate_decision_G1", True),
        ("G1_reviewer_code-reviewer", "gate_decision_G1", False),
        ("gate_decision_G1", "human_approval_G1", False),
        ("human_approval_G1", "dispatch_authors_G2", False),
        ("dispatch_authors_G2", "G2_author_requirements-agent", True),
        ("dispatch_authors_G2", "dispatch_reviewers_G2", True),
        ("G2_author_requirements-agent", "dispatch_reviewers_G2", False),
        ("dispatch_reviewers_G2", "G2_reviewer_code-reviewer", True),
        ("dispatch_reviewers_G2", "gate_decision_G2", True),
        ("G2_reviewer_code-reviewer", "gate_decision_G2", False),
        ("gate_decision_G2", "human_approval_G2", False),
        ("human_approval_G2", "dispatch_authors_G3", False),
        ("dispatch_authors_G3", "G3_author_cloud-architect", True),
        ("dispatch_authors_G3", "dispatch_reviewers_G3", True),
        ("G3_author_cloud-architect", "dispatch_reviewers_G3", False),
        ("dispatch_reviewers_G3", "G3_reviewer_code-reviewer", True),
        ("dispatch_reviewers_G3", "gate_decision_G3", True),
        ("G3_reviewer_code-reviewer", "gate_decision_G3", False),
        ("gate_decision_G3", "human_approval_G3", False),
        ("human_approval_G3", "__end__", False),
    }
    assert edges == expected_edges


def test_human_approval_treats_non_dict_resume_decision_as_not_approved(contracts):
    """`human_approval_{gate}` must fail closed (never 500) if resumed
    with a non-dict decision, mirroring `mutation_gate_check`'s existing
    isinstance guard."""
    graph = _make_graph(contracts)
    config = {"configurable": {"thread_id": "task-non-dict-decision"}}
    initial_state = {
        "task_id": "task-non-dict-decision",
        "classification": "internal",
        "scope": TASK_TEXT,
        "current_lifecycle_phase": "intent",
        "lifecycle_gates": {},
        "re_entry_history": [],
        "authorities": {
            "product_owner": {"status": "assigned"},
            "requirements_owner": {"status": "assigned"},
            "architecture_owner": {"status": "assigned"},
        },
        "agent_outputs": {},
        "mutation_gate_pending": None,
        "mutation_gate_decision": None,
        "run_halted": False,
    }
    graph.invoke(initial_state, config=config)

    result = graph.invoke(Command(resume="yes"), config=config)

    assert "__interrupt__" in result
    state = graph.get_state(config).values
    approval = state["lifecycle_gates"]["G1"]["human_approvals"][-1]
    assert approval["status"] in ("rejected", "pending")
    assert approval["approver"] is None
    assert approval["evidence_refs"] == []


def test_mutation_gate_never_fires_for_ordinary_task(contracts):
    graph = _make_mutation_graph(contracts)
    config = {"configurable": {"thread_id": "task-mutation-ordinary"}}
    initial_state = _mutation_initial_state("task-mutation-ordinary", TASK_TEXT)

    result = graph.invoke(initial_state, config=config)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload.get("kind") != "mutation_gate"
    assert payload["gate_id"] == "G1"

    state_snapshot = graph.get_state(config)
    assert state_snapshot.values["run_halted"] is False
    assert state_snapshot.values["mutation_gate_pending"] is None
