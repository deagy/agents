"""Routing configuration loading and deterministic rule matching."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Pattern


def glob_to_regex(pattern: str) -> Pattern[str]:
    """Translate the selector's small glob dialect to a compiled regex.

    Supports: * (any chars except /), ** (any path segment), ? (single char),
    [a-z] character classes, and {a,b} brace expansion (Recommendation #4).
    """
    normalized = pattern.replace("\\", "/")
    expression = "^"
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if character == "{" :
            # Brace expansion: {a,b,c} -> (a|b|c) processed in-place.
            end_brace = normalized.find("}", index)
            if end_brace != -1:
                body = normalized[index + 1 : end_brace]
                parts = [re.escape(p) for p in body.split(",")]
                expression += "(" + "|".join(parts) + ")"
                index = end_brace + 1
                continue
        if character == "[" and index + 1 < len(normalized):
            # Character class: [abc] or [!a-z] negation.
            end_bracket = normalized.find("]", index)
            if end_bracket != -1:
                class_body = normalized[index + 1 : end_bracket]
                expression += f"[{class_body}]"
                index = end_bracket + 1
                continue
        if character == "*" and index + 1 < len(normalized) and normalized[index + 1] == "*":
            index += 1
            if index + 1 < len(normalized) and normalized[index + 1] == "/":
                index += 1
                expression += "(?:.*/)?"
            else:
                expression += ".*"
        elif character == "*":
            expression += "[^/]*"
        elif character == "?":
            expression += "[^/]"
        else:
            expression += re.escape(character)
        index += 1
    return re.compile(f"{expression}$", re.IGNORECASE)


def _keyword_matches(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower()).replace(r"\ ", r"\s+")
    return re.search(rf"(^|[^a-z0-9]){escaped}([^a-z0-9]|$)", text, re.IGNORECASE) is not None


def match_rule(rule: dict[str, Any], task_text: str, changed_files: list[str]) -> dict[str, Any]:
    normalized_task = task_text.lower()
    matched_keywords = [
        keyword for keyword in rule.get("keywords", []) if _keyword_matches(normalized_task, keyword)
    ]
    matched_paths: list[dict[str, str]] = []
    for pattern in rule.get("paths", []):
        matcher = glob_to_regex(pattern)
        for file_name in changed_files:
            normalized_file = file_name.replace("\\", "/")
            if matcher.search(normalized_file):
                matched_paths.append({"pattern": pattern, "file": file_name})
    return {
        "matched": bool(matched_keywords or matched_paths),
        "keywords": matched_keywords,
        "paths": matched_paths,
    }


def load_routing(file_path: Path) -> dict[str, Any]:
    with file_path.open("r", encoding="utf-8") as source:
        config = json.load(source)
    if (
        config.get("version") != 1
        or not isinstance(config.get("routes"), list)
        or not isinstance(config.get("risk_rules"), list)
    ):
        raise ValueError("routing.yaml must contain version 1 routes and risk_rules")
    ids = [rule.get("id") for rule in [*config["routes"], *config["risk_rules"]]]
    if len(set(ids)) != len(ids):
        raise ValueError("Routing and risk rule IDs must be unique")
    return config


def load_catalog(file_path: Path) -> list[str]:
    content = file_path.read_text(encoding="utf-8")
    agents = []
    for line in content.splitlines():
        match = re.match(r"^  ([a-z0-9-]+):\s*$", line)
        if match:
            agents.append(match.group(1))
    if not agents:
        raise ValueError("No agents found in catalog.yaml")
    return agents


def match_routes(
    config: dict[str, Any], task_text: str, changed_files: list[str]
) -> list[dict[str, Any]]:
    matches = []
    for route in config["routes"]:
        reasons = match_rule(route, task_text, changed_files)
        if reasons["matched"]:
            matches.append({"id": route["id"], "reasons": reasons, "rule": route})
    return matches



