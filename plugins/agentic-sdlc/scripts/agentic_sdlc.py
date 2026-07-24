#!/usr/bin/env python3
"""Portable, standard-library bootstrap and lifecycle CLI for Agentic SDLC."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "0.1.0"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = PLUGIN_ROOT / "contracts"
PROFILES = PLUGIN_ROOT / "profiles"
EXTENSIONS = PLUGIN_ROOT / "extensions"
# Extensions are optional impact-profile add-ons. The portable kernel ships none of
# its own; this repository's own domain plugin contributes them from its own
# directory when present alongside this one, without agentic-sdlc depending on it.
EXTENSIONS_SEARCH_PATH = [EXTENSIONS, PLUGIN_ROOT.parent / "secure-cloud-agents" / "extensions"]
# Same pattern as EXTENSIONS_SEARCH_PATH: the built-in catalog covers the generic
# roles the kernel ships with; a sibling secure-cloud-agents contributes richer,
# real role definitions when present, without this plugin depending on it.
AGENT_CATALOG_SEARCH_PATH = [
    CONTRACTS / "agent-catalog.json",
    PLUGIN_ROOT.parent / "secure-cloud-agents" / "agent-catalog.json",
]
OVERLAY = ".agentic-sdlc"
GATE_IDS = [f"G{number}" for number in range(1, 11)]
REQUIRED_AUTHORITY_ROLES = {
    "product_owner": ["G1", "G2", "G6"],
    "engineering_lead": ["G2", "G6"],
    "system_architect": ["G3"],
    "governance_lead": ["G4"],
    "security_lead": ["G5"],
    "release_owner": ["G7", "G8"],
    "release_authority": ["G9"],
    "service_owner": ["G10"],
}
CONDITIONAL_AUTHORITY_ROLES = {
    "data_control_owner": ["G4"],
    "human_key_owner": ["G5"],
    "uat_product_owner": ["G6"],
    "implicated_security_lead": ["G10"],
    "implicated_governance_lead": ["G10"],
}
AUTHORITY_ROLES = {**REQUIRED_AUTHORITY_ROLES, **CONDITIONAL_AUTHORITY_ROLES}
ROLE_LABELS = {
    "product_owner": "Product Owner", "engineering_lead": "Engineering Lead",
    "system_architect": "System Architect", "governance_lead": "Governance Lead",
    "data_control_owner": "Data/Control Owner", "security_lead": "Security Lead",
    "human_key_owner": "Human Key Owner", "uat_product_owner": "Product Owner",
    "implicated_security_lead": "Security Lead",
    "implicated_governance_lead": "Governance Lead",
    "release_owner": "Release Owner", "release_authority": "Release Authority",
    "service_owner": "Service Owner",
}
MANAGED_START = "<!-- agentic-sdlc:start -->"
MANAGED_END = "<!-- agentic-sdlc:end -->"
GITHUB_REVIEW_URI = re.compile(
    r"^github-review:(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+):"
    r"pull/(?P<pull>[0-9]+):review/(?P<review>[0-9]+):reviewer/(?P<login>[A-Za-z0-9-]+)$"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_valid_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def approval_source_policy(project: dict[str, Any]) -> dict[str, Any]:
    policy = project.get("approval_sources", {})
    if not isinstance(policy, dict):
        raise ValueError("project approval_sources must be a JSON object")
    source = policy.get("human_gate_default", "manual")
    allow_manual_fallback = policy.get("allow_manual_fallback", True)
    if source not in {"manual", "github-review"}:
        raise ValueError("project approval_sources.human_gate_default must be 'manual' or 'github-review'")
    if not isinstance(allow_manual_fallback, bool):
        raise ValueError("project approval_sources.allow_manual_fallback must be a boolean")
    return {
        "human_gate_default": source,
        "allow_manual_fallback": allow_manual_fallback,
    }


def github_login_from_identity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value.startswith("github.com/"):
        login = value.removeprefix("github.com/").strip("/")
        return login or None
    return None


def authority_github_login(authority: dict[str, Any]) -> str | None:
    explicit = authority.get("github_login")
    if isinstance(explicit, str) and explicit:
        return explicit
    return github_login_from_identity(authority.get("assignee"))


def parse_github_review_uri(value: str) -> dict[str, str] | None:
    match = GITHUB_REVIEW_URI.fullmatch(value)
    if not match:
        return None
    return match.groupdict()


def normalize_commit_sha(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def fetch_github_pr_reviews(repo: str, pr: int) -> list[dict[str, Any]]:
    mock_path = os.environ.get("AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE")
    if mock_path:
        payload = json.loads(Path(mock_path).read_text(encoding="utf-8"))
    else:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/pulls/{pr}/reviews"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown gh api failure"
            raise ValueError(f"unable to fetch GitHub reviews for {repo} PR {pr}: {detail}")
        payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise ValueError("GitHub reviews response must be a JSON array")
    reviews = [item for item in payload if isinstance(item, dict)]
    if len(reviews) != len(payload):
        raise ValueError("GitHub reviews response contains non-object entries")
    return reviews


def select_github_review(
    reviews: list[dict[str, Any]], reviewer_login: str, commit_sha: str | None = None
) -> dict[str, Any]:
    normalized_login = reviewer_login.lower()
    normalized_commit = normalize_commit_sha(commit_sha)
    approved: list[dict[str, Any]] = []
    for review in reviews:
        user = review.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        state = review.get("state")
        submitted_at = review.get("submitted_at")
        review_commit = normalize_commit_sha(review.get("commit_id"))
        if not isinstance(login, str) or login.lower() != normalized_login:
            continue
        if state != "APPROVED":
            continue
        if not is_valid_datetime(submitted_at):
            continue
        if normalized_commit and review_commit != normalized_commit:
            continue
        approved.append(review)
    if not approved:
        commit_text = f" at commit {commit_sha}" if commit_sha else ""
        raise ValueError(f"no approved GitHub review found for reviewer {reviewer_login}{commit_text}")
    approved.sort(key=lambda review: str(review.get("submitted_at")))
    return approved[-1]


def human_requirement_for_gate(gate: dict[str, Any], authority_id: str) -> dict[str, Any] | None:
    for requirement in gate.get("authority_requirements", []):
        if requirement.get("authority_type") == "human-approver" and requirement.get("authority_id") == authority_id:
            return requirement
    return None


def gate_index(gate_id: str) -> int:
    return GATE_IDS.index(gate_id)


def approved_human_approvals(gate: dict[str, Any]) -> list[dict[str, Any]]:
    return [approval for approval in gate.get("human_approvals", []) if approval.get("status") == "approved"]


def has_all_required_human_approvals(gate: dict[str, Any], authorities: dict[str, Any]) -> bool:
    approvals = approved_human_approvals(gate)
    for requirement in gate.get("authority_requirements", []):
        if requirement.get("authority_type") != "human-approver" or requirement.get("applicability") != "applicable":
            continue
        authority_id = requirement.get("authority_id")
        expected_assignee = authorities.get(authority_id, {}).get("assignee")
        if not expected_assignee:
            return False
        if not any(
            isinstance(approval.get("approver"), dict)
            and approval["approver"].get("id") == expected_assignee
            and approval["approver"].get("role") == requirement.get("role")
            for approval in approvals
        ):
            return False
    return True


def can_mark_gate_approved(record: dict[str, Any], gate: dict[str, Any], authorities: dict[str, Any]) -> bool:
    if gate.get("status") not in {"ready", "approved"}:
        return False
    if gate.get("applicability") != "applicable":
        return False
    if not gate.get("artifact_bindings") or not gate.get("evidence_refs"):
        return False
    verifier = gate.get("independent_verifier")
    if not isinstance(verifier, dict):
        return False
    if not gate.get("independence_declaration", {}).get("verifier_confirmed_not_preparer"):
        return False
    gate_position = gate_index(gate["gate_id"])
    for prior in record.get("lifecycle_gates", [])[:gate_position]:
        if prior.get("applicability") != "not-applicable" and prior.get("status") != "approved":
            return False
    return has_all_required_human_approvals(gate, authorities)


def record_github_approval(
    root: Path,
    task_id: str,
    gate_id: str,
    authority_role: str,
    repo: str,
    pr: int,
    review_id: int,
    reviewer_login: str,
    commit_sha: str,
    decided_at: str | None,
) -> dict[str, Any]:
    _, project, authorities, _, _ = load_overlay(root)
    path = confined_path(root, OVERLAY, "runs", task_id, "run-record.json")
    record = load_json(path)
    approval_source_policy(project)
    gate = next((item for item in record.get("lifecycle_gates", []) if item.get("gate_id") == gate_id), None)
    if gate is None:
        raise ValueError(f"unknown gate in run record: {gate_id}")
    authority = authorities.get(authority_role)
    if not isinstance(authority, dict):
        raise ValueError(f"unknown authority role: {authority_role}")
    requirement = human_requirement_for_gate(gate, authority_role)
    if requirement is None:
        raise ValueError(f"{gate_id} does not require authority role {authority_role}")
    if requirement.get("applicability") != "applicable":
        raise ValueError(f"{gate_id} authority role {authority_role} is not applicable")
    expected_assignee = authority.get("assignee")
    if authority.get("status") != "assigned" or not expected_assignee:
        raise ValueError(f"authority {authority_role} is not assigned")
    expected_login = authority_github_login(authority)
    if expected_login and reviewer_login != expected_login:
        raise ValueError(f"GitHub reviewer {reviewer_login} does not match assigned authority login {expected_login}")
    review_uri = f"github-review:{repo}:pull/{pr}:review/{review_id}:reviewer/{reviewer_login}"
    if parse_github_review_uri(review_uri) is None:
        raise ValueError(f"invalid GitHub review URI components for {review_uri}")
    chosen_time = decided_at or now()
    if not is_valid_datetime(chosen_time):
        raise ValueError("--decided-at must be a valid RFC 3339 date-time")
    role_label = requirement.get("role")
    evidence_payload = {
        "task_id": task_id,
        "gate_id": gate_id,
        "authority_id": authority_role,
        "repo": repo,
        "pull": pr,
        "review_id": review_id,
        "reviewer_login": reviewer_login,
        "decided_at": chosen_time,
        "commit_sha": commit_sha,
    }
    approval = {
        "status": "approved",
        "approver": {"id": expected_assignee, "role": role_label, "kind": "human"},
        "decided_at": chosen_time,
        "evidence_refs": [{
            "evidence_id": f"{gate_id.lower()}-{authority_role}-github-review-{review_id}",
            "uri": review_uri,
            "hash_algorithm": "sha256",
            "hash": fingerprint(evidence_payload).removeprefix("sha256:"),
            "classification": record.get("classification", project.get("classification", "internal")),
        }],
    }
    remaining = [
        item
        for item in gate.get("human_approvals", [])
        if not (
            item.get("status") == "approved"
            and isinstance(item.get("approver"), dict)
            and item["approver"].get("id") == expected_assignee
            and item["approver"].get("role") == role_label
        )
    ]
    remaining.append(approval)
    gate["human_approvals"] = remaining
    if can_mark_gate_approved(record, gate, authorities):
        gate["status"] = "approved"
        gate["decided_at"] = max(
            [approval_item.get("decided_at") for approval_item in approved_human_approvals(gate) if approval_item.get("decided_at")] or [chosen_time]
        )
        record["current_lifecycle_phase"] = derive_current_phase(record)
    write_json(path, record)
    return {
        "task_id": task_id,
        "gate_id": gate_id,
        "authority_id": authority_role,
        "review_uri": review_uri,
        "gate_status": gate.get("status"),
        "current_phase": derive_current_phase(record),
    }


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: Any, *, overwrite: bool = True) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return True


def confined_path(root: Path, *parts: str) -> Path:
    """Resolve a project path and reject symlinks/junctions that escape the root."""
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts)
    resolved_candidate = candidate.resolve(strict=False)
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise ValueError(f"project path escapes root: {candidate}")
    return candidate


def fingerprint(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def dispatch_fingerprint(dispatch: dict[str, Any]) -> str:
    """Bind every decision-relevant dispatch field, excluding only generated metadata."""
    payload = {
        key: value
        for key, value in dispatch.items()
        if key not in {"generated_at", "dispatch_fingerprint"}
    }
    return fingerprint(payload)


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def safe_task_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) or value in {".", ".."}:
        raise ValueError("task ID must already be a portable, non-lossy ID using only letters, numbers, dot, underscore, or hyphen")
    return value


def detect_repository(root: Path) -> dict[str, Any]:
    signatures = {
        "python": ["pyproject.toml", "requirements.txt", "setup.py"],
        "node": ["package.json", "pnpm-lock.yaml", "yarn.lock"],
        "go": ["go.mod"],
        "rust": ["Cargo.toml"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "dotnet": ["*.sln", "*.csproj"],
        "terraform": ["*.tf"],
        "containers": ["Dockerfile", "compose.yaml", "docker-compose.yml"],
    }
    names = [path.name for path in root.iterdir()] if root.exists() else []
    stacks = [name for name, patterns in signatures.items() if any(any(fnmatch.fnmatch(item, pattern) for item in names) for pattern in patterns)]
    web_markers = {"package.json", "go.mod", "requirements.txt", "pyproject.toml"}
    directories = {path.name for path in root.iterdir() if path.is_dir()} if root.exists() else set()
    service_layout = bool(web_markers.intersection(names) and {"src", "app", "api", "cmd", "internal"}.intersection(directories))
    multi_tier_markers = "package.json" in names and ("go.mod" in names or "requirements.txt" in names or "pyproject.toml" in names)
    proposed = "web-service" if service_layout or multi_tier_markers else "quick"
    commands: dict[str, list[str]] = {}
    if "python" in stacks:
        commands["test"] = [sys.executable, "-m", "unittest", "discover"]
    if "node" in stacks:
        commands["test_candidate"] = ["use-project-pinned-package-manager", "test"]
    if "go" in stacks:
        commands["test"] = ["go", "test", "./..."]
        commands["static_analysis"] = ["go", "vet", "./..."]
    return {
        "root": str(root.resolve()),
        "detected_stacks": stacks,
        "directories": sorted(directories.intersection({"src", "app", "api", "cmd", "internal", "infra", "deploy"})),
        "proposed_profile": proposed,
        "command_candidates": commands,
        "warnings": ["Detection never assigns human authority or compliance applicability."],
    }


def merge_profile(profile_id: str) -> dict[str, Any]:
    path = PROFILES / profile_id / "profile.json"
    if not path.exists():
        raise ValueError(f"unknown profile: {profile_id}")
    child = load_json(path)
    parent_id = child.get("extends")
    if not parent_id:
        return child
    parent = merge_profile(str(parent_id))
    result = dict(parent)
    result.update({key: value for key, value in child.items() if key not in {"agents", "routing"}})
    result["agents"] = unique(list(parent.get("agents", [])) + list(child.get("agents", [])))
    result["routing"] = list(parent.get("routing", [])) + list(child.get("routing", []))
    result["id"] = profile_id
    return result


def managed_agents_block() -> str:
    return "\n".join([
        MANAGED_START,
        "## Agentic SDLC",
        "",
        "This repository uses the portable Agentic SDLC project overlay in `.agentic-sdlc/`.",
        "Use its orchestration skill or CLI for multi-role delivery work. Run records are authoritative.",
        "Never infer gate approval, production/destructive authority, risk acceptance, or compliance applicability.",
        "Artifact authors must remain separate from independent reviewers and human approvers.",
        MANAGED_END,
    ])


def update_agents_md(root: Path) -> None:
    path = confined_path(root, "AGENTS.md")
    block = managed_agents_block()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if (MANAGED_START in existing) != (MANAGED_END in existing):
        raise ValueError("AGENTS.md contains an incomplete Agentic SDLC managed block")
    if MANAGED_START in existing and MANAGED_END in existing:
        before, remainder = existing.split(MANAGED_START, 1)
        _, after = remainder.split(MANAGED_END, 1)
        content = before.rstrip() + "\n\n" + block + after
    else:
        content = existing.rstrip() + ("\n\n" if existing.strip() else "") + block + "\n"
    path.write_text(content, encoding="utf-8")


def toml_string(value: str) -> str:
    return json.dumps(value)


ASK_HUMAN_RULE = (
    "You are a dispatched subagent: you cannot ask the human directly. If you reach a "
    "decision only a human can make, stop and return a clearly labeled blocking question "
    "in your result instead of guessing or proceeding."
)

RICH_CONTENT_ADAPTATION_NOTE = (
    "Adapted from a cloud/GitLab-specific role definition bundled with secure-cloud-agents. "
    "Its shared-policy references (agents/shared/*.md paths) belong to that source "
    "repository and will not resolve here — review and tailor this role for this "
    "project's own stack, policies, and gates before relying on it."
)


def agent_wrapper_instructions(agent_id: str, reviewer: bool) -> str:
    return (
        f"Act as the portable Agentic SDLC role {agent_id}. "
        "Bind work to the task revision and lifecycle gate. "
        "Never approve a lifecycle or mutation gate. "
        + ("Remain independent and do not modify the artifact under review." if reviewer else "Prepare artifacts for independent review; do not self-review.")
        + " " + ASK_HUMAN_RULE
    )


def load_agent_catalog() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in AGENT_CATALOG_SEARCH_PATH:
        if path.exists():
            merged.update(load_json(path)["agents"])
    return merged


def rich_agent_content(metadata: dict[str, Any]) -> str | None:
    definition = metadata.get("definition")
    if not definition:
        return None
    path = Path(definition)
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def agent_wrapper_body(agent_id: str, reviewer: bool, metadata: dict[str, Any], profile: dict[str, Any]) -> str:
    if profile.get("rich_content_source"):
        rich = rich_agent_content(metadata)
        if rich is not None:
            return "\n\n".join([rich, RICH_CONTENT_ADAPTATION_NOTE, ASK_HUMAN_RULE])
    return agent_wrapper_instructions(agent_id, reviewer)


def write_codex_agent_wrappers(root: Path, profile: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    created: list[str] = []
    wrapper_dir = confined_path(root, ".codex", "agents")
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    for agent_id in profile.get("agents", []):
        metadata = catalog.get(agent_id)
        if not metadata:
            continue
        target = wrapper_dir / f"{agent_id}.toml"
        if target.exists():
            continue
        reviewer = metadata["kind"] == "reviewer"
        content = "\n".join([
            f"name = {toml_string(agent_id)}",
            f"description = {toml_string('Portable Agentic SDLC ' + metadata['kind'] + ' for ' + metadata['phase'])}",
            f"sandbox_mode = {toml_string('read-only' if reviewer else 'workspace-write')}",
            f"developer_instructions = {toml_string(agent_wrapper_body(agent_id, reviewer, metadata, profile))}",
            "",
        ])
        target.write_text(content, encoding="utf-8")
        created.append(str(target.relative_to(root)))
    return created


def write_claude_agent_wrappers(root: Path, profile: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    created: list[str] = []
    wrapper_dir = confined_path(root, ".claude", "agents")
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    for agent_id in profile.get("agents", []):
        metadata = catalog.get(agent_id)
        if not metadata:
            continue
        target = wrapper_dir / f"{agent_id}.md"
        if target.exists():
            continue
        reviewer = metadata["kind"] == "reviewer"
        description = "Portable Agentic SDLC " + metadata["kind"] + " for " + metadata["phase"]
        frontmatter = "\n".join([
            "---",
            f"name: {agent_id}",
            f"description: {description}",
            f"tools: {'Read, Grep, Glob, Bash' if reviewer else 'Read, Grep, Glob, Bash, Edit, Write'}",
            "---",
            "",
        ])
        target.write_text(frontmatter + agent_wrapper_body(agent_id, reviewer, metadata, profile) + "\n", encoding="utf-8")
        created.append(str(target.relative_to(root)))
    return created


def write_agent_wrappers(root: Path, profile: dict[str, Any], runner: str = "both") -> list[str]:
    catalog = load_agent_catalog()
    created: list[str] = []
    if runner in ("codex", "both"):
        created.extend(write_codex_agent_wrappers(root, profile, catalog))
    if runner in ("claude", "both"):
        created.extend(write_claude_agent_wrappers(root, profile, catalog))
    return created


def impact_item(item_id: str, extension: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "extension": extension,
        "applicability": "unknown",
        "definition_reference": None,
        "rationale": None,
        "owner": None,
        "evidence_refs": [],
    }


def initialize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    detected = detect_repository(root)
    profile_id = detected["proposed_profile"] if args.profile == "auto" else args.profile
    profile = merge_profile(profile_id)
    extension_ids = unique(args.extension or [])
    impact = [impact_item(item_id, "generic-software") for item_id in profile.get("impact_categories", [])]
    specialized_boms: list[dict[str, Any]] = []
    for extension_id in extension_ids:
        extension_path = next(
            (candidate for path in EXTENSIONS_SEARCH_PATH if (candidate := path / extension_id / "extension.json").exists()),
            None,
        )
        if extension_path is None:
            raise ValueError(f"unknown extension: {extension_id}")
        extension = load_json(extension_path)
        impact.extend(impact_item(item_id, extension_id) for item_id in extension.get("impact_categories", []))
        specialized_boms.extend(impact_item(bom, extension_id) for bom in extension.get("specialized_boms", []))
    overlay = confined_path(root, OVERLAY)
    overlay.mkdir(parents=True, exist_ok=True)
    (overlay / "runs").mkdir(exist_ok=True)
    project = {
        "schema_version": 1,
        "project_id": args.project_id or root.name,
        "classification": args.classification,
        "profile": profile_id,
        "extensions": extension_ids,
        "approval_sources": {
            "human_gate_default": "manual",
            "allow_manual_fallback": True,
        },
        "detected": detected,
        "environments": [{"name": "local", "persistence": "unknown", "production": "unknown"}],
    }
    authorities = {
        role: {
            "status": "unknown",
            "assignee": None,
            "applicability": "unknown" if role in CONDITIONAL_AUTHORITY_ROLES else "applicable",
            "rationale": None,
            "evidence_reference": None,
            "gates": gates,
        }
        for role, gates in AUTHORITY_ROLES.items()
    }
    impact_profile = {"profile_id": f"{project['project_id']}-impact", "status": "blocked", "impact_categories": impact, "specialized_boms": specialized_boms, "blocking_unknowns": [item["id"] for item in impact + specialized_boms]}
    routing = {
        "version": 1,
        "profile": profile_id,
        "routes": profile.get("routing", []),
        "change_intake": profile.get("change_intake", {}),
        "ignored_gates": profile.get("ignored_gates", []),
    }
    commands = {"version": 1, "commands": detected["command_candidates"], "confirmed": False}
    created = []
    for name, value in [("project.json", project), ("authorities.json", authorities), ("impact-profile.json", impact_profile), ("routing.json", routing), ("commands.json", commands)]:
        if write_json(overlay / name, value, overwrite=args.force):
            created.append(f"{OVERLAY}/{name}")
    lock = overlay / "version.lock"
    if args.force or not lock.exists():
        lock.write_text(
            json.dumps(
                {"plugin_version": VERSION, "kernel_version": VERSION, "contracts": 1},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        created.append(f"{OVERLAY}/version.lock")
    update_agents_md(root)
    wrappers = write_agent_wrappers(root, profile, args.runner)
    print(json.dumps({"status": "initialized", "root": str(root), "profile": profile_id, "created": created, "agent_wrappers_created": wrappers, "ready": False, "blockers": ["Human authorities and impact applicability require explicit decisions."]}, indent=2))
    return 0


def load_overlay(root: Path) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    overlay = confined_path(root, OVERLAY)
    return overlay, load_json(overlay / "project.json"), load_json(overlay / "authorities.json"), load_json(overlay / "impact-profile.json"), load_json(overlay / "routing.json")


def choose_workflow(text: str, routes: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    lowered = text.lower()
    matched = [route for route in routes if any(phrase.lower() in lowered for phrase in route.get("phrases", []))]
    if any(phrase in lowered for phrase in ["deploy to production", "production deployment"]):
        return "production-release", matched
    if any(phrase in lowered for phrase in ["major incident", "incident response", "service outage"]):
        return "support-escalation", matched
    if any(route.get("id") == "runtime-assurance" for route in matched):
        return "runtime-assurance", matched
    if any(route.get("id") == "debugging" for route in matched):
        return "debugging", matched
    intake = any(route.get("id") == "product-intake" for route in matched)
    design = any(route.get("id") not in {"product-intake", "runtime-assurance", "debugging"} for route in matched)
    if intake and not design:
        return "product-intake", matched
    if matched:
        return "new-service", matched
    return "needs-triage", matched


def lifecycle_sequence(gate_ids: list[str], ignored_gates: list[str]) -> tuple[list[str], set[str]]:
    unknown = set(ignored_gates) - set(GATE_IDS)
    if unknown:
        raise ValueError(f"ignored_gates contains unknown lifecycle gates: {sorted(unknown)}")
    if not gate_ids:
        return [], set()
    highest = max(GATE_IDS.index(gate_id) for gate_id in gate_ids)
    sequence = GATE_IDS[: highest + 1]
    ignored = set(ignored_gates).intersection(sequence)
    return sequence, ignored


def gate_agent_artifacts(gate: dict[str, Any]) -> list[dict[str, str]]:
    agents = [*gate.get("author_agents", []), *gate.get("review_agents", ["code-reviewer"])]
    return [
        {"agent_id": agent, "artifact_id": f"{gate['id'].lower()}-{agent}-attestation"}
        for agent in unique(agents)
    ]


def make_gate_record(
    gate: dict[str, Any], impact: dict[str, Any], authorities: dict[str, Any], ignored: bool = False
) -> dict[str, Any]:
    affected_unknown = bool(impact.get("blocking_unknowns")) and gate["id"] in {"G3", "G4", "G5", "G7"}
    authority_requirements = []
    for reviewer in gate.get("review_agents", ["code-reviewer"]):
        authority_requirements.append({"authority_id": reviewer, "authority_type": "independent-verifier", "role": reviewer, "applicability": "applicable", "rationale": "Required by lifecycle gate contract"})
    for authority_id in gate.get("human_authorities", []):
        assigned = authorities.get(authority_id, {}).get("status") == "assigned"
        authority_requirements.append({"authority_id": authority_id, "authority_type": "human-approver", "role": ROLE_LABELS[authority_id], "applicability": "applicable" if assigned else "unknown", "rationale": "Assigned in project authority map" if assigned else "Authority is not assigned"})
    for authority_id in gate.get("conditional_human_authorities", []):
        authority = authorities.get(authority_id, {})
        applicability = authority.get("applicability", "unknown")
        if applicability == "applicable" and authority.get("status") != "assigned":
            applicability = "unknown"
        authority_requirements.append({
            "authority_id": authority_id,
            "authority_type": "human-approver",
            "role": ROLE_LABELS[authority_id],
            "applicability": applicability,
            "rationale": authority.get("rationale") or (
                "Assigned and applicable in project authority map"
                if applicability == "applicable"
                else "Applicability requires an accountable project decision"
            ),
        })
    return {
        "tier": "lifecycle",
        "gate_id": gate["id"],
        "name": gate["name"],
        "status": "blocked" if affected_unknown else "pending",
        "applicability": "not-applicable" if ignored else ("unknown" if affected_unknown else "applicable"),
        "applicability_rationale": "Explicitly configured lifecycle gate ignore" if ignored else ("Impact applicability is unresolved" if affected_unknown else "Lifecycle gate applies by default"),
        "artifact_bindings": [],
        "preparers": [],
        "independent_verifier": None,
        "independence_declaration": {"verifier_confirmed_not_preparer": False, "verifier_made_material_correction": False},
        "authority_requirements": authority_requirements,
        "human_approvals": [],
        "decided_at": None,
        "evidence_refs": [],
        "knowledge_status": "unavailable",
        "findings": [],
        "exceptions": [],
        "invalidation_history": [],
        "required_reentry_gate": gate["id"] if affected_unknown else None,
    }


def derive_current_phase(record: dict[str, Any]) -> str:
    lifecycle = load_json(CONTRACTS / "lifecycle-gates.json")["gates"]
    phase_by_gate = {gate["id"]: gate["phase"] for gate in lifecycle}
    for gate in record.get("lifecycle_gates", []):
        if gate.get("applicability") == "not-applicable":
            continue
        if gate.get("status") != "approved":
            return phase_by_gate.get(gate.get("gate_id"), record.get("current_lifecycle_phase", "intent"))
    return "feedback"


def plan_task(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    overlay, project, authorities, impact, routing = load_overlay(root)
    workflow, matched = choose_workflow(args.task, routing.get("routes", []))
    primary: list[str] = []
    reviewers: list[str] = []
    support: list[str] = []
    gates: list[str] = []
    for route in matched:
        primary.extend(route.get("agents", []))
        reviewers.extend(route.get("reviewers", []))
        support.extend(route.get("support", []))
        gates.extend(route.get("gates", []))
    change_intake = routing.get("change_intake", {})
    normalized_task = args.task.lower()
    change_work = any(
        re.search(rf"(^|[^a-z0-9]){re.escape(keyword.lower())}([^a-z0-9]|$)", normalized_task)
        for keyword in change_intake.get("keywords", [])
    )
    if change_work:
        support.extend(change_intake.get("agents", []))
        gates.extend(change_intake.get("quality_gates", []))
    primary, reviewers, support, gates = map(unique, [primary, reviewers, support, gates])
    gates.sort(key=lambda gate_id: int(gate_id.removeprefix("G")))
    lifecycle = load_json(CONTRACTS / "lifecycle-gates.json")["gates"]
    configured_ignored = routing.get("ignored_gates", [])
    sequence, ignored_gates = lifecycle_sequence(gates, configured_ignored)
    gates = [gate_id for gate_id in sequence if gate_id not in ignored_gates]
    reviewers = [agent for agent in reviewers if agent not in primary]
    if workflow == "needs-triage":
        support = unique(support + ["requirements-agent"])
    if workflow == "production-release":
        support = unique(support + ["release-engineer"])
        gates = unique(gates + ["G8", "G9"])
    mutations = load_json(CONTRACTS / "mutation-gates.json")["human_only"]
    matched_human_gates: dict[str, dict[str, Any]] = {}
    for gate in mutations:
        for phrase in gate["phrases"]:
            if phrase in args.task.lower():
                matched_human_gates[gate["id"]] = {
                    "id": gate["id"],
                    "required": True,
                    "reason": f"Matched human-only phrase: {phrase}",
                }
    human_gates = list(matched_human_gates.values())
    required = []
    for gate_id in gates:
        contributing_routes = [route["id"] for route in matched if gate_id in route.get("gates", [])]
        if not contributing_routes:
            contributing_routes = [f"workflow:{workflow}"]
        required.append({
            "id": gate_id,
            "required": True,
            "reason": "Required by matched project route or workflow",
            "contributing_routes": contributing_routes,
        })
    gate_contracts = {gate["id"]: gate for gate in lifecycle}
    gate_agents = [
        agent
        for gate_id in sequence
        if gate_id not in ignored_gates
        for agent in [*gate_contracts[gate_id].get("author_agents", []), *gate_contracts[gate_id].get("review_agents", ["code-reviewer"])]
    ]
    support = unique(support + gate_agents)
    support = [agent for agent in support if agent not in primary and agent not in reviewers]
    gate_dispatch = [
        {
            "gate_id": gate_id,
            "status": "ignored" if gate_id in ignored_gates else "required",
            "agents": unique([*gate_contracts[gate_id].get("author_agents", []), *gate_contracts[gate_id].get("review_agents", ["code-reviewer"])]),
            "tasks": gate_contracts[gate_id].get("tasks", []),
            "artifacts": gate_contracts[gate_id].get("artifacts", []),
        }
        for gate_id in sequence
    ]
    task_id = safe_task_id(args.task_id)
    task_dir = confined_path(root, OVERLAY, "runs", task_id)
    dispatch = {
        "schema_version": 2,
        "task_id": task_id,
        "generated_at": now(),
        "status": "needs-triage" if workflow == "needs-triage" else "ready",
        "workflow": workflow,
        "inputs": {"task": args.task, "classification": project["classification"]},
        "matched_routes": [route["id"] for route in matched],
        "matched_risks": [],
        "agents": {"primary": primary, "reviewers": reviewers, "support": support},
        "required_quality_gates": required,
        "ignored_quality_gates": sorted(ignored_gates, key=GATE_IDS.index),
        "gate_dispatch": gate_dispatch,
        "human_gates": human_gates,
        "knowledge_context": {"status": "unavailable", "reason": "No portable knowledge source configured", "requests": []},
    }
    dispatch_hash = dispatch_fingerprint(dispatch)
    dispatch["dispatch_fingerprint"] = dispatch_hash
    record = {
        "version": 2,
        "task_id": task_id,
        "recorded_at": now(),
        "classification": project["classification"],
        "mode": "planning-review-only",
        "baseline_revision": "unresolved",
        "scope": args.task,
        "dispatch_fingerprint": dispatch_hash,
        "disposition": "pending",
        "intent_record_id": None,
        "requirements_baseline_id": None,
        "current_lifecycle_phase": "intent",
        "knowledge_retrieval": {"status": "unavailable", "reason": "No portable knowledge source configured", "query_ids": [], "evidence_refs": [], "influence": "none"},
        "impact_profile": impact,
        "lifecycle_gates": [make_gate_record(gate, impact, authorities, gate["id"] in ignored_gates) for gate in lifecycle],
        "specialist_attestations": [],
        "re_entry_history": [],
        "execution_summary": {
            "gates": {
                gate_id: {
                    "configured": gate_id in sequence,
                    "ignored": gate_id in ignored_gates,
                    "ignore_reason": "Configured in project routing" if gate_id in ignored_gates else None,
                    "required_agents": gate_contracts[gate_id].get("author_agents", []) + gate_contracts[gate_id].get("review_agents", ["code-reviewer"]),
                    "dispatched_agents": [],
                    "required_tasks": gate_contracts[gate_id].get("tasks", []),
                    "completed_tasks": [],
                    "required_agent_artifacts": gate_agent_artifacts(gate_contracts[gate_id]),
                    "produced_agent_artifacts": [],
                }
                for gate_id in GATE_IDS
            }
        },
    }
    dispatch_path = task_dir / "dispatch-plan.json"
    record_path = task_dir / "run-record.json"
    if dispatch_path.exists():
        existing = load_json(dispatch_path)
        existing_task = existing.get("inputs", {}).get("task")
        if existing_task != args.task:
            raise ValueError(f"task ID {task_id} already exists with different task text; use a new task ID")
        if existing.get("dispatch_fingerprint") != dispatch_hash:
            raise ValueError(f"task ID {task_id} routing has changed; use a new task ID or explicitly invalidate the existing run")
    if record_path.exists():
        existing_record = load_json(record_path)
        if existing_record.get("scope") != args.task:
            raise ValueError(f"task ID {task_id} already exists with different task text; use a new task ID")
        if existing_record.get("dispatch_fingerprint") != dispatch_hash:
            raise ValueError(f"task ID {task_id} has an existing run record for different task or routing state; use a new task ID")
    write_json(dispatch_path, dispatch)
    if not record_path.exists():
        write_json(record_path, record)
    print(json.dumps(dispatch, indent=2))
    return 0


def valid_exception(exception: dict[str, Any]) -> bool:
    required = {"exception_id", "finding_id", "justification", "compensating_controls", "owner", "approver", "expires_at", "remediation_plan"}
    if not required.issubset(exception) or not exception.get("compensating_controls"):
        return False
    owner, approver = exception.get("owner"), exception.get("approver")
    if not isinstance(owner, dict) or not isinstance(approver, dict):
        return False
    if owner.get("kind") != "human" or approver.get("kind") != "human" or owner.get("id") == approver.get("id"):
        return False
    try:
        expiry = datetime.fromisoformat(str(exception["expires_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if expiry.tzinfo is None:
        return False
    return expiry > datetime.now(timezone.utc)


def validate_repository(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    errors: list[str] = []
    blockers: list[str] = []
    try:
        import jsonschema  # type: ignore
    except ImportError:
        jsonschema = None
        errors.append(
            "full validation dependency is unavailable; install plugins/agentic-sdlc/requirements-validation.txt"
        )
    try:
        overlay, project, authorities, impact, routing = load_overlay(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "ready": False, "errors": [str(error)], "blockers": []}, indent=2))
        return 1
    if project.get("profile") not in {path.name for path in PROFILES.iterdir() if path.is_dir()}:
        errors.append("project profile is not installed")
    try:
        approval_policy = approval_source_policy(project)
    except ValueError as error:
        errors.append(str(error))
        approval_policy = {"human_gate_default": "manual", "allow_manual_fallback": True}
    for environment in project.get("environments", []):
        environment_name = environment.get("name", "unnamed")
        if environment.get("persistence") == "unknown":
            blockers.append(f"environment persistence is unknown: {environment_name}")
        if environment.get("production") == "unknown":
            blockers.append(f"environment production status is unknown: {environment_name}")
    try:
        commands = load_json(overlay / "commands.json")
        lock = load_json(overlay / "version.lock")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(str(error))
        commands, lock = {}, {}
    if commands and commands.get("confirmed") is not True:
        blockers.append("detected project commands are not confirmed")
    if lock and lock.get("kernel_version") != VERSION:
        errors.append(
            f"project kernel lock {lock.get('kernel_version')} does not match installed version {VERSION}"
        )
    for role in AUTHORITY_ROLES:
        value = authorities.get(role)
        if not isinstance(value, dict):
            errors.append(f"missing authority role: {role}")
            continue
        if role in CONDITIONAL_AUTHORITY_ROLES:
            applicability = value.get("applicability")
            if applicability == "unknown":
                blockers.append(f"conditional authority applicability {role} is unresolved")
            elif applicability == "applicable" and (
                value.get("status") != "assigned" or not value.get("assignee")
            ):
                blockers.append(f"applicable conditional authority {role} is unassigned")
            elif applicability == "not-applicable" and not value.get("rationale"):
                errors.append(f"conditional authority {role} not-applicable requires a rationale")
        elif value.get("status") != "assigned" or not value.get("assignee"):
            blockers.append(f"authority {role} is unresolved")
        if (
            value.get("status") == "assigned"
            and value.get("applicability", "applicable") == "applicable"
            and approval_policy["human_gate_default"] == "github-review"
            and not authority_github_login(value)
            and not approval_policy["allow_manual_fallback"]
        ):
            blockers.append(f"authority {role} is missing a GitHub login binding required for GitHub review approvals")
    unknown_impact = [item.get("id", "unnamed") for item in impact.get("impact_categories", []) + impact.get("specialized_boms", []) if item.get("applicability") == "unknown"]
    blockers.extend(f"impact applicability is unknown: {item}" for item in unknown_impact)
    blockers.extend(f"impact profile blocker: {item}" for item in impact.get("blocking_unknowns", []))
    route_ids: set[str] = set()
    unknown_ignored = set(routing.get("ignored_gates", [])) - set(GATE_IDS)
    if unknown_ignored:
        errors.append(f"routing ignored_gates contains unknown lifecycle gates: {sorted(unknown_ignored)}")
    agent_catalog = load_json(CONTRACTS / "agent-catalog.json")["agents"]
    known_agents = set(agent_catalog)
    for route in routing.get("routes", []):
        route_id = route.get("id")
        if not route_id or route_id in route_ids:
            errors.append(f"duplicate or missing route ID: {route_id}")
        route_ids.add(route_id)
        overlap = set(route.get("agents", [])).intersection(route.get("reviewers", []))
        if overlap:
            errors.append(f"route {route_id} assigns author and reviewer roles to: {sorted(overlap)}")
        unknown_agents = (
            set(route.get("agents", []))
            | set(route.get("reviewers", []))
            | set(route.get("support", []))
        ) - known_agents
        if unknown_agents:
            errors.append(f"route {route_id} references unknown agents: {sorted(unknown_agents)}")
    run_root = confined_path(root, OVERLAY, "runs")
    task_directories = [path for path in run_root.iterdir() if path.is_dir()] if run_root.exists() else []
    for task_directory in task_directories:
        record_path = confined_path(root, OVERLAY, "runs", task_directory.name, "run-record.json")
        dispatch_path = confined_path(root, OVERLAY, "runs", task_directory.name, "dispatch-plan.json")
        if not record_path.exists() or not dispatch_path.exists():
            errors.append(f"{task_directory}: dispatch plan and authoritative run record must both exist")
            continue
        try:
            record = load_json(record_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(str(error))
            continue
        required_top = {"version", "task_id", "dispatch_fingerprint", "recorded_at", "classification", "mode", "baseline_revision", "scope", "disposition", "intent_record_id", "requirements_baseline_id", "current_lifecycle_phase", "knowledge_retrieval", "impact_profile", "lifecycle_gates", "specialist_attestations", "re_entry_history"}
        missing_top = required_top.difference(record)
        if missing_top:
            errors.append(f"{record_path}: missing required fields: {sorted(missing_top)}")
        if jsonschema is not None:
            schema = load_json(CONTRACTS / "run-record.schema.json")
            validator = jsonschema.Draft202012Validator(
                schema,
                format_checker=jsonschema.FormatChecker(),
            )
            for schema_error in validator.iter_errors(record):
                location = ".".join(str(part) for part in schema_error.absolute_path) or "<root>"
                errors.append(f"{record_path}: schema {location}: {schema_error.message}")
        if not is_valid_datetime(record.get("recorded_at")):
            errors.append(f"{record_path}: schema recorded_at: {record.get('recorded_at')!r} is not a 'date-time'")
        gate_records = record.get("lifecycle_gates", [])
        if [gate.get("gate_id") for gate in gate_records] != GATE_IDS:
            errors.append(f"{record_path}: lifecycle gates must be exactly G1-G10 in order")
        gate_contracts = {gate["id"]: gate for gate in load_json(CONTRACTS / "lifecycle-gates.json")["gates"]}
        execution_gates = record.get("execution_summary", {}).get("gates", {})
        configured_gate_ids = {
            item.get("gate_id")
            for item in load_json(confined_path(root, OVERLAY, "runs", task_directory.name, "dispatch-plan.json")).get("gate_dispatch", [])
            if item.get("status") == "required"
        }
        ignored_gate_ids = {
            item.get("gate_id")
            for item in load_json(confined_path(root, OVERLAY, "runs", task_directory.name, "dispatch-plan.json")).get("gate_dispatch", [])
            if item.get("status") == "ignored"
        }
        invalidation_started = False
        for index, gate in enumerate(gate_records):
            gate_id = gate.get("gate_id")
            contract = gate_contracts.get(gate_id, {})
            execution = execution_gates.get(gate_id)
            if execution is None:
                errors.append(f"{record_path}: {gate_id} is missing its required execution record")
                execution = {}
            if execution is not None:
                if execution.get("configured") != (gate_id in configured_gate_ids or gate_id in ignored_gate_ids):
                    errors.append(f"{record_path}: {gate_id} execution configuration does not match dispatch plan")
                if execution.get("ignored") != (gate_id in ignored_gate_ids):
                    errors.append(f"{record_path}: {gate_id} ignore state does not match dispatch plan")
                expected_agents = unique(contract.get("author_agents", []) + contract.get("review_agents", ["code-reviewer"]))
                expected_artifacts = gate_agent_artifacts(contract)
                if execution.get("required_agents") != expected_agents:
                    errors.append(f"{record_path}: {gate_id} required agent set does not match lifecycle contract")
                if execution.get("required_tasks") != contract.get("tasks", []):
                    errors.append(f"{record_path}: {gate_id} required task set does not match lifecycle contract")
                if execution.get("required_agent_artifacts") != expected_artifacts:
                    errors.append(f"{record_path}: {gate_id} required agent artifacts do not match lifecycle contract")
                if execution.get("ignored") and not execution.get("ignore_reason"):
                    errors.append(f"{record_path}: {gate_id} ignored gate requires an explicit reason")
                if gate.get("status") in {"ready", "approved"} and execution.get("configured") and not execution.get("ignored"):
                    if set(execution.get("dispatched_agents", [])) != set(expected_agents):
                        errors.append(f"{record_path}: {gate_id} advanced without dispatching every configured agent")
                    if set(execution.get("completed_tasks", [])) != set(contract.get("tasks", [])):
                        errors.append(f"{record_path}: {gate_id} advanced without completing every configured task")
                    produced = {
                        (item.get("agent_id"), item.get("artifact_id"))
                        for item in execution.get("produced_agent_artifacts", [])
                        if item.get("revision") and item.get("digest")
                    }
                    required = {(item["agent_id"], item["artifact_id"]) for item in expected_artifacts}
                    if not required.issubset(produced):
                        errors.append(f"{record_path}: {gate_id} advanced without immutable artifacts from every configured agent")
            if gate.get("status") in {"ready", "approved"} and execution.get("configured") and any(
                prior.get("status") not in {"approved", "invalidated"}
                and execution_gates.get(prior.get("gate_id"), {}).get("configured")
                and not execution_gates.get(prior.get("gate_id"), {}).get("ignored")
                for prior in gate_records[:index]
            ):
                errors.append(f"{record_path}: {gate_id} violates lexical gate order")
            preparers = {identity.get("id") for identity in gate.get("preparers", []) if isinstance(identity, dict)}
            verifier = gate.get("independent_verifier")
            if isinstance(verifier, dict) and verifier.get("id") in preparers:
                errors.append(f"{record_path}: {gate_id} verifier is also a preparer")
            if gate.get("independence_declaration", {}).get("verifier_made_material_correction"):
                errors.append(f"{record_path}: {gate_id} verifier made a material correction and lost approval authority")
            if invalidation_started and gate.get("status") != "invalidated":
                errors.append(f"{record_path}: downstream gate {gate_id} must be invalidated")
            if gate.get("status") == "invalidated":
                invalidation_started = True
                if not gate.get("required_reentry_gate"):
                    errors.append(f"{record_path}: {gate_id} invalidation is missing required re-entry gate")
            if gate.get("decided_at") is not None and not is_valid_datetime(gate.get("decided_at")):
                errors.append(f"{record_path}: schema lifecycle_gates.{index}.decided_at: {gate.get('decided_at')!r} is not a 'date-time'")
            for approval_index, approval in enumerate(gate.get("human_approvals", [])):
                if approval.get("decided_at") is not None and not is_valid_datetime(approval.get("decided_at")):
                    errors.append(
                        f"{record_path}: schema lifecycle_gates.{index}.human_approvals.{approval_index}.decided_at: "
                        f"{approval.get('decided_at')!r} is not a 'date-time'"
                    )
            for invalidation_index, invalidation in enumerate(gate.get("invalidation_history", [])):
                if not is_valid_datetime(invalidation.get("invalidated_at")):
                    errors.append(
                        f"{record_path}: schema lifecycle_gates.{index}.invalidation_history.{invalidation_index}.invalidated_at: "
                        f"{invalidation.get('invalidated_at')!r} is not a 'date-time'"
                    )
            for exception_index, exception in enumerate(gate.get("exceptions", [])):
                if not is_valid_datetime(exception.get("expires_at")):
                    errors.append(
                        f"{record_path}: schema lifecycle_gates.{index}.exceptions.{exception_index}.expires_at: "
                        f"{exception.get('expires_at')!r} is not a 'date-time'"
                    )
            if gate.get("status") == "approved":
                if any(
                    prior.get("status") != "approved"
                    and prior.get("applicability") != "not-applicable"
                    for prior in gate_records[:index]
                ):
                    errors.append(f"{record_path}: {gate_id} approved before all prerequisite gates")
                if gate.get("applicability") != "applicable" or not gate.get("evidence_refs") or not gate.get("artifact_bindings"):
                    errors.append(f"{record_path}: {gate_id} has an unsafe approval without applicability, evidence, or artifact binding")
                requirements = gate.get("authority_requirements", [])
                requirement_ids: set[str] = set()
                for requirement in requirements:
                    authority_id = requirement.get("authority_id")
                    if authority_id in requirement_ids:
                        errors.append(f"{record_path}: {gate_id} has duplicate authority requirement {authority_id}")
                    requirement_ids.add(authority_id)
                    if authority_id in ROLE_LABELS and (
                        requirement.get("authority_type") != "human-approver"
                        or requirement.get("role") != ROLE_LABELS[authority_id]
                    ):
                        errors.append(f"{record_path}: {gate_id} authority {authority_id} is relabeled")
                    if requirement.get("applicability") == "not-applicable" and not requirement.get("rationale"):
                        errors.append(f"{record_path}: {gate_id} not-applicable authority {authority_id} lacks rationale")
                gate_contract = gate_contracts.get(gate_id, {})
                expected_reviewers = gate_contract.get("review_agents", ["code-reviewer"])
                expected_requirement_ids = set(expected_reviewers)
                expected_requirement_ids.update(gate_contract.get("human_authorities", []))
                expected_requirement_ids.update(gate_contract.get("conditional_human_authorities", []))
                missing_requirements = expected_requirement_ids - requirement_ids
                if missing_requirements:
                    errors.append(
                        f"{record_path}: {gate_id} is missing authority requirements "
                        f"{sorted(missing_requirements)}"
                    )
                if any(requirement.get("applicability") == "unknown" for requirement in requirements):
                    errors.append(f"{record_path}: {gate_id} approved with unresolved authority applicability")
                if not isinstance(verifier, dict) or not gate.get("independence_declaration", {}).get("verifier_confirmed_not_preparer"):
                    errors.append(f"{record_path}: {gate_id} lacks an independent verifier declaration")
                required_reviewers = set(gate_contracts.get(gate_id, {}).get("review_agents", ["code-reviewer"]))
                verifier_role = verifier.get("role") if isinstance(verifier, dict) else None
                if not isinstance(verifier, dict) or verifier_role not in required_reviewers:
                    errors.append(f"{record_path}: {gate_id} lacks required reviewer role {sorted(required_reviewers)}")
                elif agent_catalog.get(verifier_role, {}).get("kind") != "reviewer":
                    errors.append(f"{record_path}: {gate_id} verifier role is not a catalog reviewer")
                approvals = [approval for approval in gate.get("human_approvals", []) if approval.get("status") == "approved"]
                approval_roles = {approval.get("approver", {}).get("role") for approval in approvals if isinstance(approval.get("approver"), dict)}
                required_roles = {ROLE_LABELS[role] for role in gate_contracts.get(gate_id, {}).get("human_authorities", [])}
                required_roles.update(
                    requirement.get("role")
                    for requirement in requirements
                    if requirement.get("authority_type") == "human-approver"
                    and requirement.get("applicability") == "applicable"
                )
                if not required_roles.issubset(approval_roles):
                    errors.append(f"{record_path}: {gate_id} lacks required human roles {sorted(required_roles - approval_roles)}")
                for approval in gate.get("human_approvals", []):
                    approver = approval.get("approver")
                    if approval.get("status") == "approved" and (not isinstance(approver, dict) or approver.get("kind") != "human"):
                        errors.append(f"{record_path}: {gate_id} approval is not human")
                    if isinstance(approver, dict) and (approver.get("id") in preparers or (isinstance(verifier, dict) and approver.get("id") == verifier.get("id"))):
                        errors.append(f"{record_path}: {gate_id} approver is not independent")
                    if approval.get("status") == "approved" and (
                        not approval.get("decided_at") or not approval.get("evidence_refs")
                    ):
                        errors.append(f"{record_path}: {gate_id} approval lacks decision time or approval evidence")
                    github_review_refs = []
                    for evidence in approval.get("evidence_refs", []):
                        uri = evidence.get("uri")
                        if isinstance(uri, str) and uri.startswith("github-review:"):
                            parsed_review = parse_github_review_uri(uri)
                            if parsed_review is None:
                                errors.append(f"{record_path}: {gate_id} approval has an invalid GitHub review URI")
                            else:
                                github_review_refs.append(parsed_review)
                    if approval.get("status") == "approved":
                        if (
                            approval_policy["human_gate_default"] == "github-review"
                            and not approval_policy["allow_manual_fallback"]
                            and not github_review_refs
                        ):
                            errors.append(f"{record_path}: {gate_id} approval must be backed by a GitHub review")
                        if github_review_refs and isinstance(approver, dict):
                            approver_login = github_login_from_identity(approver.get("id"))
                            for parsed_review in github_review_refs:
                                if approver_login and approver_login != parsed_review["login"]:
                                    errors.append(f"{record_path}: {gate_id} GitHub review login does not match approver identity")
                for requirement in requirements:
                    if requirement.get("authority_type") != "human-approver" or requirement.get("applicability") != "applicable":
                        continue
                    authority_id = requirement.get("authority_id")
                    expected_assignee = authorities.get(authority_id, {}).get("assignee")
                    matching = [
                        approval for approval in approvals
                        if isinstance(approval.get("approver"), dict)
                        and approval["approver"].get("id") == expected_assignee
                        and approval["approver"].get("role") == requirement.get("role")
                    ]
                    if not expected_assignee or not matching:
                        errors.append(f"{record_path}: {gate_id} approval is not bound to assigned authority {authority_id}")
                    expected_github_login = authority_github_login(authorities.get(authority_id, {}))
                    if expected_github_login:
                        for approval in matching:
                            github_review_refs = [
                                parsed_review
                                for evidence in approval.get("evidence_refs", [])
                                for parsed_review in [parse_github_review_uri(evidence.get("uri", ""))]
                                if parsed_review is not None
                            ]
                            if github_review_refs and any(parsed_review["login"] != expected_github_login for parsed_review in github_review_refs):
                                errors.append(f"{record_path}: {gate_id} approval GitHub reviewer does not match assigned authority {authority_id}")
                if not gate.get("decided_at"):
                    errors.append(f"{record_path}: {gate_id} approved without a gate decision timestamp")
                if any(not binding.get("digest") for binding in gate.get("artifact_bindings", [])):
                    errors.append(f"{record_path}: {gate_id} approved with a mutable artifact binding")
                open_severe = [finding for finding in gate.get("findings", []) if finding.get("severity") in {"critical", "high"} and finding.get("status") == "open"]
                if open_severe:
                    errors.append(f"{record_path}: {gate_id} has unresolved critical/high findings")
                exception_findings = {exception.get("finding_id") for exception in gate.get("exceptions", []) if valid_exception(exception)}
                for finding in gate.get("findings", []):
                    if finding.get("status") == "accepted-exception" and finding.get("finding_id") not in exception_findings:
                        errors.append(f"{record_path}: {gate_id} accepted finding lacks a valid exception")
                if gate_id in {"G3", "G4", "G5", "G7"} and record.get("impact_profile", {}).get("blocking_unknowns"):
                    errors.append(f"{record_path}: {gate_id} approved while impact applicability is unknown")
        for invalidation_index, invalidation in enumerate(record.get("re_entry_history", [])):
            if not is_valid_datetime(invalidation.get("invalidated_at")):
                errors.append(
                    f"{record_path}: schema re_entry_history.{invalidation_index}.invalidated_at: "
                    f"{invalidation.get('invalidated_at')!r} is not a 'date-time'"
                )
    for task_directory in task_directories:
        dispatch_path = confined_path(root, OVERLAY, "runs", task_directory.name, "dispatch-plan.json")
        record_path = confined_path(root, OVERLAY, "runs", task_directory.name, "run-record.json")
        if not dispatch_path.exists() or not record_path.exists():
            continue
        try:
            dispatch = load_json(dispatch_path)
            record = load_json(record_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(str(error))
            continue
        if jsonschema is not None:
            schema = load_json(CONTRACTS / "selection.schema.json")
            validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
            for schema_error in validator.iter_errors(dispatch):
                location = ".".join(str(part) for part in schema_error.absolute_path) or "<root>"
                errors.append(f"{dispatch_path}: schema {location}: {schema_error.message}")
        if dispatch.get("task_id") != record.get("task_id") or dispatch.get("task_id") != task_directory.name:
            errors.append(f"{task_directory}: task IDs do not match directory, dispatch, and run record")
        if dispatch.get("inputs", {}).get("task") != record.get("scope"):
            errors.append(f"{task_directory}: dispatch task and run-record scope do not match")
        if dispatch.get("dispatch_fingerprint") != record.get("dispatch_fingerprint"):
            errors.append(f"{task_directory}: dispatch and run-record fingerprints do not match")
        computed_fingerprint = dispatch_fingerprint(dispatch)
        if dispatch.get("dispatch_fingerprint") != computed_fingerprint:
            errors.append(f"{dispatch_path}: stored dispatch fingerprint does not match current dispatch content")
        overlap = set(dispatch.get("agents", {}).get("primary", [])).intersection(dispatch.get("agents", {}).get("reviewers", []))
        if overlap:
            errors.append(f"{dispatch_path}: dispatch author/reviewer overlap: {sorted(overlap)}")
        expected_sequence = dispatch.get("gate_dispatch", [])
        required_ids = [gate.get("id") for gate in dispatch.get("required_quality_gates", [])]
        dispatched_required_ids = [item.get("gate_id") for item in expected_sequence if item.get("status") == "required"]
        dispatched_ignored_ids = [item.get("gate_id") for item in expected_sequence if item.get("status") == "ignored"]
        if required_ids != dispatched_required_ids:
            errors.append(f"{dispatch_path}: required quality gates do not match gate dispatch")
        if dispatch.get("ignored_quality_gates", []) != dispatched_ignored_ids:
            errors.append(f"{dispatch_path}: configured ignored gates do not match gate dispatch")
        if [item.get("gate_id") for item in expected_sequence] != [
            item.get("gate_id") for item in sorted(expected_sequence, key=lambda item: GATE_IDS.index(item.get("gate_id")))
        ]:
            errors.append(f"{dispatch_path}: gate dispatch must be in lexical order")
        execution_gates = record.get("execution_summary", {}).get("gates", {})
        for item in expected_sequence:
            gate_id = item.get("gate_id")
            execution = execution_gates.get(gate_id)
            if item.get("status") == "ignored":
                if not execution or not execution.get("ignored") or not execution.get("ignore_reason"):
                    errors.append(f"{dispatch_path}: ignored {gate_id} lacks explicit execution waiver")
                continue
            if execution and execution.get("ignored"):
                errors.append(f"{dispatch_path}: required {gate_id} is marked ignored in the run record")
            if execution:
                if execution.get("required_tasks") != item.get("tasks"):
                    errors.append(f"{dispatch_path}: {gate_id} task dispatch does not match the lifecycle contract")
                if {artifact["artifact_id"] for artifact in execution.get("required_agent_artifacts", [])} != {
                    f"{gate_id.lower()}-{agent}-attestation" for agent in item.get("agents", [])
                }:
                    errors.append(f"{dispatch_path}: {gate_id} artifact dispatch does not match configured agents")
    result = {"valid": not errors, "ready": not errors and not blockers, "errors": errors, "blockers": blockers}
    print(json.dumps(result, indent=2))
    if errors:
        return 1
    return 2 if blockers else 0


def status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    task_id = safe_task_id(args.task_id)
    record = load_json(confined_path(root, OVERLAY, "runs", task_id, "run-record.json"))
    gates = [{"gate_id": gate["gate_id"], "status": gate["status"], "applicability": gate["applicability"], "required_reentry_gate": gate.get("required_reentry_gate")} for gate in record["lifecycle_gates"]]
    print(json.dumps({"task_id": task_id, "current_phase": derive_current_phase(record), "gates": gates, "re_entry_history": record["re_entry_history"]}, indent=2))
    return 0


def invalidate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    task_id = safe_task_id(args.task_id)
    path = confined_path(root, OVERLAY, "runs", task_id, "run-record.json")
    record = load_json(path)
    start = GATE_IDS.index(args.earliest_gate)
    invalidated = GATE_IDS[start:]
    stamp = now()
    for gate in record["lifecycle_gates"]:
        if gate["gate_id"] in invalidated:
            gate["status"] = "invalidated"
            gate["required_reentry_gate"] = args.earliest_gate
    record["current_lifecycle_phase"] = load_json(CONTRACTS / "lifecycle-gates.json")["gates"][start]["phase"]
    affected_bindings = [
        binding
        for gate in record["lifecycle_gates"][start:]
        for binding in gate.get("artifact_bindings", [])
    ]
    history = {
        "invalidated_at": stamp,
        "actor": args.actor,
        "reason": args.reason,
        "earliest_gate": args.earliest_gate,
        "invalidated_gate_ids": invalidated,
        "affected_artifact_bindings": affected_bindings,
        "superseding_artifact_id": None,
    }
    record["re_entry_history"].append(history)
    for gate in record["lifecycle_gates"][start:]:
        gate["invalidation_history"].append(history)
    write_json(path, record)
    print(json.dumps({"task_id": task_id, "earliest_gate": args.earliest_gate, "invalidated_gate_ids": invalidated}, indent=2))
    return 0


def approve_from_github(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    task_id = safe_task_id(args.task_id)
    result = record_github_approval(
        root,
        task_id,
        args.gate,
        args.role,
        args.repo,
        args.pr,
        args.review_id,
        args.reviewer_login,
        args.commit_sha,
        args.decided_at,
    )
    print(json.dumps(result, indent=2))
    return 0


def approve_from_github_pr(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    task_id = safe_task_id(args.task_id)
    _, _, authorities, _, _ = load_overlay(root)
    authority = authorities.get(args.role)
    if not isinstance(authority, dict):
        raise ValueError(f"unknown authority role: {args.role}")
    reviewer_login = args.reviewer_login or authority_github_login(authority)
    if not reviewer_login:
        raise ValueError(f"authority {args.role} has no GitHub login binding and --reviewer-login was not supplied")
    reviews = fetch_github_pr_reviews(args.repo, args.pr)
    review = select_github_review(reviews, reviewer_login, args.commit_sha)
    review_id = review.get("id")
    submitted_at = review.get("submitted_at")
    commit_sha = review.get("commit_id")
    if not isinstance(review_id, int):
        raise ValueError("selected GitHub review is missing a numeric id")
    if not is_valid_datetime(submitted_at):
        raise ValueError("selected GitHub review is missing a valid submitted_at timestamp")
    if not isinstance(commit_sha, str) or not commit_sha:
        raise ValueError("selected GitHub review is missing a commit_id")
    result = record_github_approval(
        root,
        task_id,
        args.gate,
        args.role,
        args.repo,
        args.pr,
        review_id,
        reviewer_login,
        commit_sha,
        submitted_at,
    )
    result["selected_review_id"] = review_id
    result["selected_commit_sha"] = commit_sha
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-sdlc", description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)
    detect = subparsers.add_parser("detect", help="Detect repository stack without changing files")
    detect.add_argument("--root", default=".")
    detect.set_defaults(handler=lambda args: (print(json.dumps(detect_repository(Path(args.root)), indent=2)) or 0))
    init = subparsers.add_parser("init", help="Initialize a conservative project overlay")
    init.add_argument("--root", default=".")
    init.add_argument("--profile", choices=["auto"] + sorted(path.name for path in PROFILES.iterdir() if path.is_dir()), default="auto")
    init.add_argument("--extension", action="append", help="Enable an impact-profile extension by id (resolved at init time; see EXTENSIONS_SEARCH_PATH)")
    init.add_argument("--project-id")
    init.add_argument("--classification", default="internal")
    init.add_argument("--runner", choices=["codex", "claude", "both"], default="both", help="Which agent runner(s) to generate subagent wrappers for")
    init.add_argument("--force", action="store_true", help="Refresh managed overlay files; never overwrites custom agent wrappers")
    init.set_defaults(handler=initialize)
    plan = subparsers.add_parser("plan", help="Create a dispatch plan and pending run record")
    plan.add_argument("--root", default=".")
    plan.add_argument("--task-id", required=True)
    plan.add_argument("--task", required=True)
    plan.set_defaults(handler=plan_task)
    validate = subparsers.add_parser("validate", help="Validate configuration and fail closed on unresolved decisions")
    validate.add_argument("--root", default=".")
    validate.set_defaults(handler=validate_repository)
    show = subparsers.add_parser("status", help="Show a task's gate state")
    show.add_argument("--root", default=".")
    show.add_argument("--task-id", required=True)
    show.set_defaults(handler=status)
    approve = subparsers.add_parser("approve-from-github", help="Record a human gate approval from a GitHub PR review")
    approve.add_argument("--root", default=".")
    approve.add_argument("--task-id", required=True)
    approve.add_argument("--gate", choices=GATE_IDS, required=True)
    approve.add_argument("--role", choices=sorted(AUTHORITY_ROLES), required=True, help="Authority role recording the approval")
    approve.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    approve.add_argument("--pr", type=int, required=True, help="Pull request number")
    approve.add_argument("--review-id", type=int, required=True, help="GitHub review identifier")
    approve.add_argument("--reviewer-login", required=True, help="GitHub login that authored the review")
    approve.add_argument("--commit-sha", required=True, help="Commit SHA reviewed by the GitHub approval")
    approve.add_argument("--decided-at", help="Approval time in RFC 3339 format; defaults to now")
    approve.set_defaults(handler=approve_from_github)
    approve_auto = subparsers.add_parser("approve-from-github-pr", help="Fetch an approved GitHub PR review and record it as human gate approval evidence")
    approve_auto.add_argument("--root", default=".")
    approve_auto.add_argument("--task-id", required=True)
    approve_auto.add_argument("--gate", choices=GATE_IDS, required=True)
    approve_auto.add_argument("--role", choices=sorted(AUTHORITY_ROLES), required=True, help="Authority role recording the approval")
    approve_auto.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    approve_auto.add_argument("--pr", type=int, required=True, help="Pull request number")
    approve_auto.add_argument("--reviewer-login", help="GitHub login to match; defaults to the authority GitHub binding")
    approve_auto.add_argument("--commit-sha", help="Optional commit SHA to require when selecting an approved review")
    approve_auto.set_defaults(handler=approve_from_github_pr)
    invalid = subparsers.add_parser("invalidate", help="Invalidate the earliest affected gate and all downstream gates")
    invalid.add_argument("--root", default=".")
    invalid.add_argument("--task-id", required=True)
    invalid.add_argument("--earliest-gate", choices=GATE_IDS, required=True)
    invalid.add_argument("--reason", required=True)
    invalid.add_argument("--actor", required=True, help="Accountable identity recording the invalidation")
    invalid.set_defaults(handler=invalidate)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
