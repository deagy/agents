"""Risk matching and cross-stack support selection."""

from __future__ import annotations

from typing import Any

from routing import match_rule


def classify_risks(
    config: dict[str, Any], task_text: str, changed_files: list[str]
) -> list[dict[str, Any]]:
    matches = []
    for risk in config["risk_rules"]:
        reasons = match_rule(risk, task_text, changed_files)
        if reasons["matched"]:
            matches.append({"id": risk["id"], "reasons": reasons, "rule": risk})
    return matches


def apply_cross_stack(config: dict[str, Any], matched_routes: list[dict[str, Any]]) -> list[str]:
    cross_stack = config.get("cross_stack")
    if not cross_stack:
        return []
    relevant = [route for route in matched_routes if route["id"] in cross_stack["route_ids"]]
    if len(relevant) < cross_stack["minimum_matches"]:
        return []
    return cross_stack.get("support", [])
