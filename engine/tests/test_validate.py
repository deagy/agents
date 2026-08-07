"""Tests for `validate_run_record` (agentic_sdlc_langgraph.validate), the
gate-record-only residual slice of the legacy CLI's `validate_repository`.

Fixtures are built via `export.export_run_record` (feeding a hand-built
`lifecycle_gates` dict for whichever gates are under test, and
`sequence_gate_ids` restricted to those gates so the rest export as
realistic "not-applicable" placeholders) rather than constructing raw
run-record dicts by hand, so these tests exercise `validate_run_record`
against the same shape this project's own export pipeline actually
produces.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentic_sdlc_langgraph.export import export_run_record
from agentic_sdlc_langgraph.validate import validate_run_record

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "plugins" / "agentic-sdlc" / "contracts"

SCHEMA = json.loads((CONTRACTS / "run-record.schema.json").read_text(encoding="utf-8"))

_ZERO_DIGEST = "sha256:" + "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity(id_: str, role: str) -> dict[str, Any]:
    return {"id": id_, "role": role, "kind": "agent" if id_ != "product_owner" else "human"}


def _evidence(evidence_id: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "uri": f"fake://evidence/{evidence_id}",
        "hash_algorithm": "sha256",
        "hash": "0" * 64,
        "classification": "internal",
    }


def _artifact_binding(artifact_id: str) -> dict[str, Any]:
    return {"artifact_id": artifact_id, "revision": "rev-1", "digest": _ZERO_DIGEST}


def _valid_approved_gate(gate_id: str) -> dict[str, Any]:
    """A fully-approved, schema-valid, invariant-clean G1-shaped gate."""
    return {
        "tier": "lifecycle",
        "gate_id": gate_id,
        "name": "Intent",
        "applicability": "applicable",
        "applicability_rationale": "Lifecycle gate applies by default",
        "status": "approved",
        "artifact_bindings": [_artifact_binding(f"{gate_id}-artifact")],
        "preparers": [_identity("product-intent-agent", "author:product-intent-agent")],
        "independent_verifier": _identity("code-reviewer", "reviewer:code-reviewer"),
        "independence_declaration": {
            "verifier_confirmed_not_preparer": True,
            "verifier_made_material_correction": False,
        },
        "authority_requirements": [
            {
                "authority_id": "product_owner",
                "authority_type": "human-approver",
                "role": "Product Owner",
                "applicability": "applicable",
                "rationale": "Assigned in project authority map",
            }
        ],
        "human_approvals": [
            {
                "status": "approved",
                "approver": _identity("product_owner", "Product Owner"),
                "decided_at": _now(),
                "evidence_refs": [_evidence(f"{gate_id}-approval-evidence")],
            }
        ],
        "decided_at": _now(),
        "evidence_refs": [_evidence(f"{gate_id}-evidence")],
        "knowledge_status": "unavailable",
        "findings": [],
        "exceptions": [],
        "invalidation_history": [],
        "required_reentry_gate": None,
    }


def _record(lifecycle_gates: dict[str, dict[str, Any]], sequence_gate_ids: list[str]) -> dict[str, Any]:
    state = {
        "task_id": "validate-test",
        "classification": "internal",
        "scope": "validate a small task",
        "lifecycle_gates": lifecycle_gates,
        "re_entry_history": [],
    }
    return export_run_record(state, sequence_gate_ids=sequence_gate_ids)


def test_fully_valid_approved_record_returns_ok():
    gate = _valid_approved_gate("G1")
    record = _record({"G1": gate}, sequence_gate_ids=["G1"])
    gate_contracts = {"G1": {"authority_requirements": ["product_owner"]}}

    code, messages = validate_run_record(record, SCHEMA, gate_contracts=gate_contracts)

    assert (code, messages) == (0, [])


def test_approved_gate_missing_evidence_refs_is_a_hard_error():
    gate = _valid_approved_gate("G1")
    gate["evidence_refs"] = []
    record = _record({"G1": gate}, sequence_gate_ids=["G1"])

    code, messages = validate_run_record(record, SCHEMA)

    assert code != 0
    assert any("evidence_refs" in message for message in messages)


def test_unresolved_authority_applicability_is_a_blocker_not_an_error():
    gate = _valid_approved_gate("G1")
    gate["authority_requirements"][0]["applicability"] = "unknown"
    gate["authority_requirements"][0]["rationale"] = None
    record = _record({"G1": gate}, sequence_gate_ids=["G1"])

    code, messages = validate_run_record(record, SCHEMA)

    assert code == 2, f"expected a blocker (code 2), got {code}: {messages}"
    assert any("unresolved authority applicability" in message for message in messages)
    # Distinguishable from a hard error: no message should read as a
    # structural defect for this otherwise-complete gate.
    assert not any("missing" in message.lower() and "G1" in message for message in messages)


def test_downstream_of_invalidation_cascade_fires_when_later_gate_not_invalidated():
    g1 = _valid_approved_gate("G1")
    g1["status"] = "invalidated"
    g1["required_reentry_gate"] = "G1"

    g2 = _valid_approved_gate("G2")
    g2["status"] = "pending"  # deliberately NOT invalidated -- the bug under test
    g2["human_approvals"] = []
    g2["decided_at"] = None

    record = _record({"G1": g1, "G2": g2}, sequence_gate_ids=["G1", "G2"])

    code, messages = validate_run_record(record, SCHEMA)

    assert code == 1
    assert any(
        "G2" in message and "must be invalidated" in message for message in messages
    ), messages


def test_verifier_that_is_also_a_preparer_is_an_error_regardless_of_status():
    gate = _valid_approved_gate("G1")
    gate["independent_verifier"] = dict(gate["preparers"][0])
    gate["independence_declaration"]["verifier_confirmed_not_preparer"] = False
    record = _record({"G1": gate}, sequence_gate_ids=["G1"])

    code, messages = validate_run_record(record, SCHEMA)

    assert code == 1
    assert any("also a preparer" in message for message in messages)


def test_approver_matching_preparer_is_not_independent():
    gate = _valid_approved_gate("G1")
    gate["human_approvals"][0]["approver"] = _identity(
        "product-intent-agent", "author:product-intent-agent"
    )
    record = _record({"G1": gate}, sequence_gate_ids=["G1"])

    code, messages = validate_run_record(record, SCHEMA)

    assert code == 1
    assert any("not independent" in message for message in messages)


def test_missing_contract_authority_requirement_is_an_error_when_contracts_supplied():
    gate = _valid_approved_gate("G1")
    record = _record({"G1": gate}, sequence_gate_ids=["G1"])
    gate_contracts = {"G1": {"authority_requirements": ["product_owner", "engineering_lead"]}}

    code, messages = validate_run_record(record, SCHEMA, gate_contracts=gate_contracts)

    assert code == 1
    assert any("missing authority requirements" in message for message in messages)


def test_invalid_timestamp_is_caught_even_though_format_checker_is_a_noop_here():
    """Empirically, `jsonschema.FormatChecker()` does not actually
    register a `date-time` checker in this project's venv (the optional
    `rfc3339-validator` dependency isn't installed) -- so a malformed
    `decided_at` must be caught by the hand-rolled check, not the schema
    pass alone."""
    gate = _valid_approved_gate("G1")
    gate["decided_at"] = "not-a-real-timestamp"
    record = _record({"G1": gate}, sequence_gate_ids=["G1"])

    code, messages = validate_run_record(record, SCHEMA)

    assert code == 1
    assert any("decided_at" in message and "not-a-real-timestamp" in message for message in messages)
