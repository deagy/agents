"""Loaders for the declarative Agentic SDLC contracts, and the two small
phrase-matching predicates ported from `agentic_sdlc.py`.

These are read-only ports against the reference files under
`plugins/agentic-sdlc/contracts/` and `providers/agentic-sdlc-defaults/`.
Nothing here writes to those trees.

Simplification: `load_profile` returns the profile JSON as-is. The legacy
`merge_profile`'s `extends`-chain logic (following a profile's `extends`
field across multiple manifest files) is **not** ported — this spike only
ever loads the single `generic` profile directly, which has no `extends`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_lifecycle_gates(path: str | Path) -> list[dict[str, Any]]:
    """Return the `gates` array from `lifecycle-gates.json`."""
    return _load_json(path)["gates"]


def load_mutation_gates(path: str | Path) -> list[dict[str, Any]]:
    """Return the `human_only` array from `mutation-gates.json`."""
    return _load_json(path)["human_only"]


def load_agent_catalog(path: str | Path) -> dict[str, Any]:
    """Return the `agents` mapping (agent_id -> {"kind", "capabilities"})
    from `agent-catalog.json`."""
    return _load_json(path)["agents"]


def load_profile(path: str | Path) -> dict[str, Any]:
    """Return the full profile document (`gate_bindings` + `routing`, etc.)

    No `extends`-chain merge (see module docstring) — generic profile only.
    """
    return _load_json(path)


def gate_dispatch_binding(gate: dict[str, Any], gate_bindings: dict[str, Any]) -> dict[str, list[str]]:
    """Port of `agentic_sdlc.py`'s `gate_dispatch_binding` (~962-972).

    Resolves the agents/tasks/artifacts bound to a gate's
    `required_contributions` slots via the profile's `gate_bindings`.
    """
    result: dict[str, list[str]] = {"agents": [], "tasks": [], "artifacts": []}
    binding = gate_bindings.get(gate["id"], {})
    contributions = binding.get("contributions", {}) if isinstance(binding, dict) else {}
    for slot in gate.get("required_contributions", []):
        contribution = contributions.get(slot)
        if not isinstance(contribution, dict):
            continue
        for field in result:
            for value in contribution.get(field, []):
                if value not in result[field]:
                    result[field].append(value)
    return result


def choose_route(task_text: str, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Simplified port of `choose_workflow`'s phrase-matching (~883-900).

    Only the "which route objects match this task text" part is ported —
    the full workflow-name derivation (production-release / support-
    escalation / runtime-assurance / debugging / product-intake / ...) is
    out of scope for this spike; we only need the matched route objects to
    resolve reviewer dispatch.
    """
    lowered = task_text.lower()
    return [
        route
        for route in routes
        if any(phrase.lower() in lowered for phrase in route.get("phrases", []))
    ]


def mutation_gate_guard(task_text: str, mutation_gates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Port of `plan_task`'s mutation-gate phrase-matching loop (~1010-1020).

    Returns None if no human-only phrase matches; otherwise a dict with a
    `matched` list of `{"id", "phrase", "reason"}` entries (one per matched
    mutation-gate id — mirrors the original's `matched_human_gates` dict,
    just collected into a list since dict key-uniqueness is preserved by
    only recording first-match-per-gate-id here as well).
    """
    lowered = task_text.lower()
    matched: dict[str, dict[str, Any]] = {}
    for gate in mutation_gates:
        for phrase in gate.get("phrases", []):
            if phrase in lowered:
                matched[gate["id"]] = {
                    "id": gate["id"],
                    "phrase": phrase,
                    "reason": f"Matched human-only phrase: {phrase}",
                }
                break
    if not matched:
        return None
    return {"matched": list(matched.values())}
