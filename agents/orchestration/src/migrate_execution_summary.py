"""Migrate legacy portable run records to the complete execution index."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN_SCRIPT = ROOT / "plugins" / "agentic-sdlc" / "scripts"
sys.path.insert(0, str(PLUGIN_SCRIPT))

from agentic_sdlc import dispatch_fingerprint  # noqa: E402


GATE_IDS = [f"G{index}" for index in range(1, 11)]
CONTRACT_PATH = ROOT / "plugins" / "agentic-sdlc" / "contracts" / "lifecycle-gates.json"
RUNS = ROOT / ".agentic-sdlc" / "runs"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _dispatch_entries(dispatch: dict, contracts: dict[str, dict]) -> tuple[list[str], list[str], list[dict]]:
    required = [item["id"] if isinstance(item, dict) else item for item in dispatch.get("required_quality_gates", [])]
    ignored = list(dispatch.get("ignored_quality_gates", []))
    if not required and not ignored:
        return [], [], []
    highest = max(GATE_IDS.index(gate_id) for gate_id in [*required, *ignored])
    sequence = GATE_IDS[: highest + 1]
    ignored_set = set(ignored)
    entries = []
    for gate_id in sequence:
        contract = contracts[gate_id]
        agents = _unique(contract.get("author_agents", []) + contract.get("review_agents", ["code-reviewer"]))
        entries.append({
            "gate_id": gate_id,
            "status": "ignored" if gate_id in ignored_set else "required",
            "agents": agents,
            "tasks": contract.get("tasks", []),
            "artifacts": contract.get("artifacts", []),
        })
    return [gate_id for gate_id in sequence if gate_id not in ignored_set], ignored, entries


def _execution_index(
    existing: dict, configured: list[str], ignored: list[str], contracts: dict[str, dict]
) -> dict[str, dict]:
    result = {}
    for gate_id in GATE_IDS:
        contract = contracts[gate_id]
        agents = _unique(contract.get("author_agents", []) + contract.get("review_agents", ["code-reviewer"]))
        prior = existing.get(gate_id, {})
        result[gate_id] = {
            "configured": gate_id in configured or gate_id in ignored,
            "ignored": gate_id in ignored,
            "ignore_reason": (
                prior.get("ignore_reason") or "Configured in project routing"
                if gate_id in ignored else None
            ),
            "required_agents": agents,
            "dispatched_agents": prior.get("dispatched_agents", []),
            "required_tasks": contract.get("tasks", []),
            "completed_tasks": prior.get("completed_tasks", []),
            "required_agent_artifacts": [
                {"agent_id": agent, "artifact_id": f"{gate_id.lower()}-{agent}-attestation"}
                for agent in agents
            ],
            "produced_agent_artifacts": prior.get("produced_agent_artifacts", []),
        }
    return result


def migrate_run(path: Path, contracts: dict[str, dict]) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    dispatch_path = path.with_name("dispatch-plan.json")
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    configured, ignored, entries = _dispatch_entries(dispatch, contracts)
    dispatch["ignored_quality_gates"] = ignored
    dispatch["gate_dispatch"] = entries
    dispatch["dispatch_fingerprint"] = dispatch_fingerprint(dispatch)
    dispatch_path.write_text(json.dumps(dispatch, indent=2) + "\n", encoding="utf-8")

    record["dispatch_fingerprint"] = dispatch["dispatch_fingerprint"]
    record["execution_summary"] = {"gates": _execution_index(
        record.get("execution_summary", {}).get("gates", {}), configured, ignored, contracts
    )}
    for gate in record.get("lifecycle_gates", []):
        if gate.get("status") in {"ready", "approved"}:
            execution = record["execution_summary"]["gates"].get(gate.get("gate_id"), {})
            if (
                set(execution.get("dispatched_agents", [])) != set(execution.get("required_agents", []))
                or set(execution.get("completed_tasks", [])) != set(execution.get("required_tasks", []))
                or not execution.get("produced_agent_artifacts")
            ):
                gate["required_reentry_gate"] = "G1"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    contracts = {item["id"]: item for item in json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["gates"]}
    for record_path in sorted(RUNS.glob("*/run-record.json")):
        migrate_run(record_path, contracts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
