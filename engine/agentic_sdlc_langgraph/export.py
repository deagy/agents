"""Reassemble the checkpointed graph state into a `run-record.schema.json`
shaped dict, and validate it.

Phase 1: all ten lifecycle gates (G1-G10) can now be modeled live in the
graph (see `graph.py` / `planning.py`), so this module no longer
synthesizes a blanket "G4-G10 not-applicable" placeholder the way the
Phase-0 spike did. Instead, for each of the fixed G1..G10 schema slots:

- If the gate has a real entry in `state["lifecycle_gates"]` (i.e. it was
  actually part of the built graph and at least reached
  `gate_decision_{gate_id}`), that real `GateState` is exported as-is.
- If the gate id is in `ignored_gate_ids` (the caller's record of what
  `derive_gate_sequence` excluded via its `ignored_gate_ids` argument), it
  is synthesized as an `applicability: "not-applicable"` placeholder --
  the task legitimately never needed this gate.
- If the gate id is simply outside `sequence_gate_ids` (the gate list
  `derive_gate_sequence` actually returned and that was fed to
  `build_graph`) -- i.e. beyond the highest gate any matched route
  referenced -- it is likewise synthesized as `"not-applicable"`.
- Otherwise (in-sequence, not ignored, but the graph hasn't reached it
  yet -- e.g. an earlier gate is still pending approval, or the run was
  halted at the mutation-gate guard before any gate dispatched) it is
  synthesized as an `applicability: "applicable"`, `status: "pending"`
  placeholder. This is the important correction from Phase 0: an
  in-sequence gate that just hasn't run yet must never be exported as
  "not-applicable" -- that would misrepresent it as out of scope rather
  than merely not-yet-decided.

`sequence_gate_ids` defaults to all of G1..G10 (i.e. "assume every gate
is in scope unless the caller says otherwise"), so callers that always
build the graph with the full chain (or don't care to distinguish
"beyond derived sequence" from "not yet reached") can omit it entirely.

Several top-level required fields this project doesn't yet compute
faithfully (`dispatch_fingerprint`, `contract_digest`,
`dispatch_binding_digest`, `provider_bindings`, `knowledge_retrieval`,
`impact_profile`, `specialist_attestations`, ...) are still filled with
fixed placeholders -- modeling those is later-phase work per the
architecture plan.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_ZERO_DIGEST = "sha256:" + "0" * 64

ALL_GATE_IDS = [f"G{n}" for n in range(1, 11)]

_GATE_NAMES = {
    "G1": "Intent",
    "G2": "Requirements Baseline",
    "G3": "Architecture",
    "G4": "Governance and Data",
    "G5": "Security and Crypto",
    "G6": "Verification and Test",
    "G7": "Evidence",
    "G8": "Release Readiness",
    "G9": "Deployment Authorization",
    "G10": "Runtime Conformance",
}

_PHASE_BY_GATE_ID = {
    "G1": "intent",
    "G2": "requirements",
    "G3": "architecture",
    "G4": "governance-data",
    "G5": "security-crypto",
    "G6": "verify",
    "G7": "evidence",
    "G8": "release-readiness",
    "G9": "deployment-authorization",
    "G10": "runtime-conformance",
}


def _base_placeholder_gate(gate_id: str) -> dict[str, Any]:
    return {
        "tier": "lifecycle",
        "gate_id": gate_id,
        "name": _GATE_NAMES[gate_id],
        "applicability": "applicable",
        "applicability_rationale": None,
        "status": "pending",
        "artifact_bindings": [],
        "preparers": [],
        "independent_verifier": None,
        "independence_declaration": {
            "verifier_confirmed_not_preparer": False,
            "verifier_made_material_correction": False,
        },
        "authority_requirements": [],
        "human_approvals": [],
        "decided_at": None,
        "evidence_refs": [],
        "knowledge_status": "unavailable",
        "findings": [],
        "exceptions": [],
        "invalidation_history": [],
        "required_reentry_gate": None,
    }


def _pending_placeholder_gate(gate_id: str) -> dict[str, Any]:
    """In-sequence, applicable, but not yet reached by the graph."""
    gate = _base_placeholder_gate(gate_id)
    gate["applicability_rationale"] = (
        "Lifecycle gate is in the derived sequence for this task but has "
        "not yet been reached"
    )
    return gate


def _not_applicable_placeholder_gate(gate_id: str, rationale: str) -> dict[str, Any]:
    gate = _base_placeholder_gate(gate_id)
    gate["applicability"] = "not-applicable"
    gate["applicability_rationale"] = rationale
    gate["knowledge_status"] = "not-applicable"
    return gate


def _execution_summary_gate(
    gate_id: str,
    *,
    configured: bool,
    ignored: bool,
    ignore_reason: str | None,
    gate_bindings: dict[str, Any] | None,
) -> dict[str, Any]:
    binding = (gate_bindings or {}).get(gate_id, {})
    contributions = binding.get("contributions", {}) if isinstance(binding, dict) else {}
    required_agents: list[str] = []
    required_tasks: list[str] = []
    for contribution in contributions.values():
        if not isinstance(contribution, dict):
            continue
        for agent in contribution.get("agents", []):
            if agent not in required_agents:
                required_agents.append(agent)
        for task in contribution.get("tasks", []):
            if task not in required_tasks:
                required_tasks.append(task)
    return {
        "configured": configured,
        "ignored": ignored,
        "ignore_reason": ignore_reason,
        "required_agents": required_agents if configured else [],
        "dispatched_agents": [],
        "required_tasks": required_tasks if configured else [],
        "completed_tasks": [],
        "required_agent_artifacts": [],
        "produced_agent_artifacts": [],
    }


def export_run_record(
    state: dict[str, Any],
    all_gate_ids: list[str] | None = None,
    sequence_gate_ids: list[str] | None = None,
    ignored_gate_ids: list[str] | None = None,
    gate_bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a schema-shaped run-record dict from graph state.

    `all_gate_ids` (default G1..G10) is the full fixed lifecycle sequence
    the schema requires exactly 10 entries for.

    `sequence_gate_ids` is the gate-id list actually fed into
    `build_graph` for this run (typically `derive_gate_sequence`'s
    return, mapped to ids) -- defaults to all of `all_gate_ids` (assume
    everything is in scope) if not given.

    `ignored_gate_ids` is whatever `derive_gate_sequence` was called with
    -- used only to pick a more specific "explicitly ignored" rationale
    for the not-applicable placeholder; a gate outside `sequence_gate_ids`
    but not in `ignored_gate_ids` still gets a not-applicable placeholder
    (it was simply never referenced by any matched route).
    """
    all_gate_ids = all_gate_ids or ALL_GATE_IDS
    sequence_gate_ids = set(sequence_gate_ids) if sequence_gate_ids is not None else set(all_gate_ids)
    ignored_gate_ids = set(ignored_gate_ids or [])
    modeled_gates: dict[str, Any] = state.get("lifecycle_gates", {})

    lifecycle_gates = []
    execution_summary_gates = {}
    for gid in all_gate_ids:
        if gid in modeled_gates:
            lifecycle_gates.append(modeled_gates[gid])
            execution_summary_gates[gid] = _execution_summary_gate(
                gid, configured=True, ignored=False, ignore_reason=None, gate_bindings=gate_bindings
            )
        elif gid in ignored_gate_ids:
            lifecycle_gates.append(
                _not_applicable_placeholder_gate(
                    gid, "Explicitly excluded via ignored_gate_ids"
                )
            )
            execution_summary_gates[gid] = _execution_summary_gate(
                gid,
                configured=False,
                ignored=True,
                ignore_reason="Explicitly excluded via ignored_gate_ids",
                gate_bindings=gate_bindings,
            )
        elif gid not in sequence_gate_ids:
            lifecycle_gates.append(
                _not_applicable_placeholder_gate(
                    gid, "Not part of the derived gate sequence for this task"
                )
            )
            execution_summary_gates[gid] = _execution_summary_gate(
                gid, configured=False, ignored=False, ignore_reason=None, gate_bindings=gate_bindings
            )
        else:
            lifecycle_gates.append(_pending_placeholder_gate(gid))
            execution_summary_gates[gid] = _execution_summary_gate(
                gid, configured=True, ignored=False, ignore_reason=None, gate_bindings=gate_bindings
            )

    # current_lifecycle_phase: first non-approved, applicable gate's phase;
    # "feedback" if every applicable gate is approved.
    current_phase = "feedback"
    for gate in lifecycle_gates:
        if gate["applicability"] == "not-applicable":
            continue
        if gate["status"] != "approved":
            current_phase = _PHASE_BY_GATE_ID.get(gate["gate_id"], "intent")
            break

    return {
        "version": 2,
        "task_id": state.get("task_id", "unknown-task"),
        "dispatch_fingerprint": _ZERO_DIGEST,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "classification": state.get("classification") or "unclassified",
        "mode": "langgraph-phase1",
        "baseline_revision": "unresolved",
        "scope": state.get("scope") or "unspecified",
        "disposition": "pending",
        "intent_record_id": state.get("intent_record_id"),
        "requirements_baseline_id": state.get("requirements_baseline_id"),
        "current_lifecycle_phase": current_phase,
        "knowledge_retrieval": {
            "status": "unavailable",
            "reason": "No portable knowledge source configured in this project",
            "query_ids": [],
            "evidence_refs": [],
            "influence": "none",
        },
        "impact_profile": {
            "profile_id": "phase1-langgraph",
            "status": "draft",
            "impact_categories": [],
            "specialized_boms": [],
            "blocking_unknowns": [],
        },
        "lifecycle_gates": lifecycle_gates,
        "specialist_attestations": [],
        "re_entry_history": state.get("re_entry_history", []),
        "execution_summary": {"gates": execution_summary_gates},
        "kernel_version": "0.1.0-langgraph-phase1",
        "contract_digest": _ZERO_DIGEST,
        "provider_bindings": [],
        "profile": "generic",
        "profile_digest": None,
        "dispatch_binding_digest": _ZERO_DIGEST,
    }
