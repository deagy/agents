"""Build the stable version 2 agent dispatch-plan document."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from risk_classifier import apply_cross_stack, classify_risks
from routing import match_routes

CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
MAXIMUM_KNOWLEDGE_TOP = 20
KNOWLEDGE_STORE_ROOT = Path(__file__).resolve().parents[2] / "knowledge-store"
DEFAULT_KNOWLEDGE_SOURCE = Path(__file__).resolve().parents[3].name


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _ordered(values: Iterable[str], catalog: list[str]) -> list[str]:
    positions = {agent: index for index, agent in enumerate(catalog)}
    return sorted(_unique(values), key=lambda agent: positions.get(agent, len(catalog)))


def _reasons(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "keywords": match["reasons"]["keywords"],
        "paths": match["reasons"]["paths"],
    }


def _select_workflow(route_ids: list[str], risk_ids: list[str], has_agents: bool) -> str:
    if not has_agents:
        return "needs-triage"
    if "production" in risk_ids:
        return "production-release"
    if "support" in route_ids or "incident-response" in route_ids:
        return "support-escalation"
    if "runtime-assurance" in route_ids:
        return "runtime-assurance"
    if "knowledge-store" in route_ids and all(
        route_id in {"knowledge-store", "documentation", "testing"} for route_id in route_ids
    ):
        return "knowledge-ingestion"
    if "agent-suite-governance" in route_ids:
        return "debugging"
    if "debugging" in route_ids:
        return "debugging"
    product_intake_routes = {
        "product-intent",
        "requirements-baseline",
        "documentation",
        "testing",
    }
    if (
        any(route_id in {"product-intent", "requirements-baseline"} for route_id in route_ids)
        and all(route_id in product_intake_routes for route_id in route_ids)
        and "architecture-change" not in risk_ids
    ):
        return "product-intake"
    if "infrastructure" in route_ids and not any(
        route_id in {"frontend", "backend", "pipeline"} for route_id in route_ids
    ):
        return "infrastructure-change"
    if "pipeline" in route_ids and not any(
        route_id in {"frontend", "backend", "infrastructure"} for route_id in route_ids
    ):
        return "pipeline-change"
    return "new-service"


def _build_human_gates(risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    descriptions = {
        "persistent-database-migration": "An authorized human must approve persistent database migrations.",
        "production-change": "An authorized human must approve the exact production change and target.",
        "destructive-action": "An authorized human must approve the exact destructive action and recovery plan.",
        "accountable-human-escalation": "An accountable human owner or approval group must make the requested decision.",
        "privileged-identity-change": "An authorized human must approve privileged identity, credential, or break-glass changes.",
    }
    gate_ids = _unique(
        risk["rule"].get("human_gate")
        for risk in risks
        if risk["rule"].get("human_gate")
    )
    return [
        {
            "id": gate_id,
            "required": True,
            "reason": descriptions.get(gate_id, "An authorized human decision is required."),
        }
        for gate_id in gate_ids
    ]


def _build_quality_gates(
    config: dict[str, Any], routes: list[dict[str, Any]], risks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Aggregate lifecycle gates without conflating them with human mutation gates."""
    definitions = config.get("quality_gates", {})
    contributors: dict[str, list[str]] = {}
    for match in [*routes, *risks]:
        for gate_id in match["rule"].get("quality_gates", []):
            if gate_id not in definitions:
                raise ValueError(f"Routing references an unknown quality gate: {gate_id}")
            contributors.setdefault(gate_id, []).append(match["id"])

    def gate_order(gate_id: str) -> tuple[int, str]:
        suffix = gate_id.removeprefix("G")
        return (int(suffix), gate_id) if suffix.isdigit() else (999, gate_id)

    return [
        {
            "id": gate_id,
            "required": True,
            "reason": definitions[gate_id],
            "contributing_routes": _unique(contributors[gate_id]),
        }
        for gate_id in sorted(contributors, key=gate_order)
    ]


def _build_knowledge_context(
    config: dict[str, Any], selected_agents: list[str], input_data: dict[str, Any]
) -> dict[str, Any]:
    if not selected_agents:
        return {"status": "not-applicable", "requests": []}
    classification = input_data.get("classification")
    if not classification:
        return {
            "status": "authorization-required",
            "reason": "Provide an authorized classification and scope before retrieval.",
            "requests": [],
        }
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"Invalid classification: {classification}")
    try:
        top = int(input_data.get("top", 5))
    except (TypeError, ValueError) as error:
        raise ValueError("Knowledge top must be an integer from 1 through 20") from error
    if not 1 <= top <= MAXIMUM_KNOWLEDGE_TOP:
        raise ValueError("Knowledge top must be an integer from 1 through 20")

    requests = []
    normalized_task = " ".join(input_data["task"].split())
    for agent in selected_agents:
        focus = config["knowledge_focus"].get(agent)
        if not focus:
            raise ValueError(f"Missing knowledge focus for selected agent: {agent}")
        query = f"Task: {normalized_task}. Retrieve {focus}."
        args = [
            "src/cli.py",
            "context",
            "--agent",
            agent,
            "--task-id",
            input_data["task_id"],
            "--query",
            query,
            "--classification",
            classification,
            "--top",
            str(top),
            "--source",
            input_data.get("source") or DEFAULT_KNOWLEDGE_SOURCE,
        ]
        requests.append(
            {
                "agent": agent,
                "query": query,
                "invocation": {
                    "cwd": str(KNOWLEDGE_STORE_ROOT),
                    "launcher": {
                        "runtime": "python",
                        "minimum_version": "3.10",
                        "resolution": "runner-probed",
                    },
                    "args": args,
                },
            }
        )
    return {
        "status": "planned",
        "classification": classification,
        "source_filter": input_data.get("source"),
        "requests": requests,
    }


def _validate_agents(groups: dict[str, list[str]], catalog: list[str]) -> None:
    known = set(catalog)
    for agent in [*groups["primary"], *groups["reviewers"], *groups["support"]]:
        if agent not in known:
            raise ValueError(f"Routing selected an unknown agent: {agent}")


def build_dispatch_plan(
    config: dict[str, Any], catalog: list[str], input_data: dict[str, Any]
) -> dict[str, Any]:
    matched_routes = match_routes(config, input_data["task"], input_data["changed_files"])
    matched_risks = classify_risks(config, input_data["task"], input_data["changed_files"])
    primary = [agent for match in matched_routes for agent in match["rule"].get("primary", [])]
    reviewers = [agent for match in matched_routes for agent in match["rule"].get("reviewers", [])]
    support = [agent for match in matched_routes for agent in match["rule"].get("support", [])]
    for risk in matched_risks:
        primary.extend(risk["rule"].get("primary", []))
        reviewers.extend(risk["rule"].get("reviewers", []))
        support.extend(risk["rule"].get("support", []))
    support.extend(apply_cross_stack(config, matched_routes))

    groups = {
        "primary": _ordered(primary, catalog),
        "reviewers": _ordered(reviewers, catalog),
        "support": _ordered(support, catalog),
    }
    groups["reviewers"] = [agent for agent in groups["reviewers"] if agent not in groups["primary"]]
    groups["support"] = [
        agent
        for agent in groups["support"]
        if agent not in groups["primary"] and agent not in groups["reviewers"]
    ]
    _validate_agents(groups, catalog)

    selected_agents = _ordered(
        [*groups["primary"], *groups["reviewers"], *groups["support"]], catalog
    )
    route_ids = [route["id"] for route in matched_routes]
    risk_ids = [risk["id"] for risk in matched_risks]
    task_id = input_data.get("task_id")
    if not task_id:
        changed_file_fingerprint = "\n".join(input_data["changed_files"])
        fingerprint = f"{input_data['task']}\n{changed_file_fingerprint}"
        task_id = f"local-{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:12]}"
    normalized_input = {**input_data, "task_id": task_id}
    generated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    return {
        "schema_version": 2,
        "task_id": task_id,
        "generated_at": generated_at,
        "status": "ready" if selected_agents else "needs-triage",
        "workflow": _select_workflow(route_ids, risk_ids, bool(selected_agents)),
        "inputs": {
            "task": input_data["task"],
            "base": input_data.get("base"),
            "changed_file_source": input_data["changed_file_source"],
            "changed_files": input_data["changed_files"],
            "classification": input_data.get("classification"),
            "source_filter": input_data.get("source"),
        },
        "matched_routes": [{"id": match["id"], "reasons": _reasons(match)} for match in matched_routes],
        "matched_risks": [{"id": match["id"], "reasons": _reasons(match)} for match in matched_risks],
        "agents": groups,
        "required_quality_gates": _build_quality_gates(config, matched_routes, matched_risks),
        "human_gates": _build_human_gates(matched_risks),
        "knowledge_context": _build_knowledge_context(config, selected_agents, normalized_input),
    }
