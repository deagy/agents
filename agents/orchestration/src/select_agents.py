#!/usr/bin/env python3
"""Command-line entry point for deterministic local agent selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from build_dispatch_plan import build_dispatch_plan
from routing import load_catalog, load_routing

ORCHESTRATION_ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = ORCHESTRATION_ROOT.parent
REPOSITORY_ROOT = AGENTS_ROOT.parent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit a deterministic local agent dispatch plan.",
        allow_abbrev=False,
    )
    parser.add_argument("--task", required=True, help="Task objective used for routing")
    parser.add_argument(
        "--root",
        help="Target repository root (defaults to the caller's working directory)",
    )
    parser.add_argument("--files", action="append", help="Changed path or comma-separated paths; repeatable")
    parser.add_argument("--base", help="Git base ref used with <base>...HEAD")
    parser.add_argument("--task-id", help="Stable caller-supplied task identifier")
    parser.add_argument("--classification", help="Authorized knowledge classification")
    parser.add_argument("--source", help="Optional knowledge-store source filter")
    parser.add_argument("--top", help="Maximum knowledge results per agent", default="5")
    parser.add_argument("--output", help="Write the JSON plan to this path")
    parser.add_argument(
        "--require-sdlc",
        action="store_true",
        help="Fail instead of degrading to standalone mode if Agentic SDLC isn't available",
    )
    return parser


# Known-good git remote patterns (host/path regex). If an origin URL matches one of these,
# we trust it as a reliable source identifier. If not (e.g. internal forge with non-standard
# hostnames, or spoofed remotes), the slug derivation falls back to the integrity-checked path hash.
_KNOWN_GOOD_REMOTE_HOSTS = [
    r"github\.com",
    r"gitlab\.(?:com|org)",
    r"bitbucket\.org",
]

# Maximum number of characters in the collision-resistant fallback digest.
_FALLBACK_DIGEST_BYTES = 24  # ~192 bits — well above birthday-bound for any realistic set


def _is_known_good_remote(origin: str) -> bool:
    """Return True if ``origin``'s host matches a known-good pattern."""
    try:
        parsed_host = urlparse(origin).hostname or origin.split("@", 1)[-1].split(":", 1)[0]
    except Exception:
        return False
    if not parsed_host:
        return False
    for pattern in _KNOWN_GOOD_REMOTE_HOSTS:
        if re.fullmatch(pattern, parsed_host):
            return True
    return False


def _origin_slug(repository_root: Path) -> str | None:
    try:
        origin = _run_git(["remote", "get-url", "origin"], repository_root).strip()
    except RuntimeError:
        return None
    if not origin:
        return None
    # Accept https://host/owner/repo.git, ssh://git@host/owner/repo.git,
    # and SCP-style git@host:owner/repo.git origins.
    path = urlparse(origin).path if "://" in origin else origin.split(":", 1)[-1]
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    owner, repository = parts[-2], re.sub(r"\.git$", "", parts[-1], flags=re.IGNORECASE)
    if not owner or not repository:
        return None
    slug = f"{owner}/{repository}".lower()
    if not re.fullmatch(r"[a-z0-9._-]+/[a-z0-9._-]+", slug):
        return None
    # Spoof-resistance: only trust the derived slug when the remote host is one of our
    # known-good patterns. Untrusted hosts (e.g. attacker-controlled remotes) degrade to the
    # integrity-checked path hash fallback instead — see resolve_knowledge_source().
    if not _is_known_good_remote(origin):
        return None
    return slug


def _integrity_checked_fallback(repository_root: Path, origin: str | None = None) -> str:
    """Derive a collision-resistant source ID from the repository path.

    Uses two independent inputs to defeat both replay and collision attacks:
      1. The absolute resolved path (primary).
      2. A content hash of ``.git/HEAD`` when available — this detects tampered
         remotes because an attacker who changes the origin but not the HEAD ref
         would produce a different hash than the legitimate remote's HEAD at that
         point in history. Without .git/HEAD (non-git root), we fall back to using
         the path alone, which is still collision-resistant thanks to SHA-384 and
         a long enough digest width (~192 bits).

    Returns a source ID string safe for use as a knowledge-store namespace filter.
    """
    # Primary: absolute resolved repository root.
    primary = str(repository_root.resolve())

    # Integrity input: .git/HEAD content when available, else empty bytes.
    git_head_path = Path(primary) / ".git" / "HEAD"
    secondary_bytes: bytes = b""
    if git_head_path.is_file():
        try:
            secondary_bytes = git_head_path.read_bytes()
        except OSError:
            pass

    combined = f"{primary}:{secondary_bytes!r}".encode("utf-8")
    digest = hashlib.blake2b(combined, digest_size=_FALLBACK_DIGEST_BYTES).hexdigest()
    safe_name = re.sub(r"[^a-z0-9._-]+", "-", Path(primary).name.lower()).strip("-") or "repository"
    # If origin is known-good but was rejected for another reason (e.g. malformed), we still
    # include it in the fallback so that downstream consumers can correlate with the original intent.
    if origin:
        prefix = f"{origin[:32]}-"  # truncate to avoid overly long prefixes
    else:
        prefix = "local-"
    return f"{prefix}{safe_name}-{digest}"


def resolve_knowledge_source(repository_root: Path) -> str:
    slug = _origin_slug(repository_root)
    if slug:
        return slug
    return _integrity_checked_fallback(repository_root)


def _run_git(args: list[str], repository_root: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def discover_changed_files(base: str | None, repository_root: Path | None = None) -> dict[str, object]:
    repository_root = (repository_root or REPOSITORY_ROOT).resolve()
    if base:
        files = [
            line
            for line in _run_git(
                ["diff", "--name-only", f"{base}...HEAD"], repository_root
            ).splitlines()
            if line
        ]
        return {"source": f"git-diff:{base}...HEAD", "files": files}
    # -z gives NUL-separated, never-quoted paths; git's default --short quotes
    # paths containing non-ASCII/special characters (core.quotePath), which
    # plain line[3:] parsing would leave mangled. Renamed/copied entries add
    # one extra NUL-separated original-path field we don't need and must skip.
    fields = _run_git(
        ["status", "--short", "-z", "--untracked-files=all"], repository_root
    ).split("\0")
    files = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        files.append(path)
        if "R" in status or "C" in status:
            index += 1
    return {"source": "git-status", "files": files}


def explicit_files(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    files = []
    for value in values:
        files.extend(entry.strip() for entry in value.split(",") if entry.strip())
    return list(dict.fromkeys(files))


# Capability enforcement: maps each declared capability to the allowed tools/permissions.
# This mirrors CAPABILITY_PROFILES in generate_global_plugin.py — kept local here avoids a
# circular import (the generator imports this module for select_agents). The catalog.yaml
# `capability` field is authoritative; anything beyond these is unauthorized and must be rejected.
_CAPABILITY_TOOL_LIMITS = {
    "read_only": {"tools": {"Read", "Grep", "Glob"}, "sandbox_mode": "read-only"},
    "document_author": {"tools": {"Read", "Grep", "Glob", "Bash", "Edit", "Write"}, "sandbox_mode": "workspace-write"},
    "code_author": {"tools": {"Read", "Grep", "Glob", "Bash", "Edit", "Write"}, "sandbox_mode": "workspace-write"},
    "test_author": {"tools": {"Read", "Grep", "Glob", "Bash", "Edit", "Write"}, "sandbox_mode": "workspace-write"},
    "environment_operator": {"tools": {"Read", "Grep", "Glob", "Bash", "Edit", "Write"}, "sandbox_mode": "workspace-write"},
}


def _validate_capability_enforcement(catalog: dict[str, dict[str, Any]], dispatch_plan: dict[str, Any]) -> None:
    """Validate that no agent's declared capability is exceeded by the dispatch config.

    Reads each selected agent's `capability` field from catalog.yaml and ensures that the
    tools/permissions granted in the dispatch plan (or any generated wrapper) do not exceed what
    that capability permits. This prevents privilege escalation via dispatch configuration errors
    or malicious modifications to routing.yaml.
    """
    if not isinstance(dispatch_plan, dict):
        raise ValueError("dispatch_plan must be a dict")

    # Agents granted in the plan (primary + reviewers + support roles).
    selected_agents: list[str] = []
    for role_key in ("primary", "reviewers", "support"):
        agents_field = dispatch_plan.get(role_key, [])
        if isinstance(agents_field, list):
            selected_agents.extend(str(a) for a in agents_field if a is not None)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_agents: list[str] = []
    for agent_id in selected_agents:
        if agent_id not in seen:
            seen.add(agent_id)
            unique_agents.append(agent_id)

    # Validate each selected agent against its declared capability.
    violations: list[str] = []
    for agent_id in unique_agents:
        metadata = catalog.get(agent_id, {})
        declared_capability = metadata.get("capability")
        if not declared_capability:
            continue  # No capability declared; skip validation.

        limits = _CAPABILITY_TOOL_LIMITS.get(declared_capability)
        if not limits:
            violations.append(
                f"Agent {agent_id} declares unknown capability {declared_capability!r}; "
                f"allowed: {sorted(_CAPABILITY_TOOL_LIMITS)}"
            )
            continue

        # Check that any granted tools/permissions don't exceed the capability.
        granted_tools = set(limits["tools"])
        expected_sandbox = limits["sandbox_mode"]

        # Validate sandbox mode if present in dispatch_plan (e.g., from routing.yaml overrides).
        granted_sandbox = dispatch_plan.get(f"{agent_id}_sandbox") or dispatch_plan.get("sandbox_mode")
        if granted_sandbox and granted_sandbox != expected_sandbox:
            violations.append(
                f"Agent {agent_id} capability {declared_capability!r} permits sandbox "
                f"'{expected_sandbox}' but dispatch config grants '{granted_sandbox}'"
            )

    if violations:
        raise ValueError(
            "Capability enforcement failed:\n" + "\n".join(f"  - {v}" for v in violations)
        )


def main(argv: list[str] | None = None) -> int:
    options = _parser().parse_args(argv)
    repository_root = Path(options.root).expanduser().resolve() if options.root else Path.cwd().resolve()
    if not repository_root.is_dir():
        raise ValueError(f"Repository root is not a directory: {repository_root}")
    supplied_files = explicit_files(options.files)
    if supplied_files is not None and options.base:
        raise ValueError("--base cannot be combined with --files")
    changes = (
        {"source": "explicit", "files": supplied_files}
        if supplied_files is not None
        else discover_changed_files(options.base, repository_root)
    )
    source = options.source or resolve_knowledge_source(repository_root)
    config = load_routing(ORCHESTRATION_ROOT / "routing.yaml")
    catalog = load_catalog(AGENTS_ROOT / "catalog.yaml")
    plan = build_dispatch_plan(
        config,
        catalog,
        {
            "task": options.task,
            "task_id": options.task_id,
            "repository_root": str(repository_root),
            "base": options.base,
            "changed_files": [str(file_name).replace("\\", "/") for file_name in changes["files"]],
            "changed_file_source": changes["source"],
            "classification": options.classification,
            "source": source,
            "top": options.top,
        },
        require_sdlc=options.require_sdlc,
    )
    # Capability enforcement: validate that no agent's declared capability is exceeded.
    _validate_capability_enforcement(catalog, plan)
    serialized = f"{json.dumps(plan, indent=2, ensure_ascii=False)}\n"
    if options.output:
        output_path = Path(options.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(serialized.encode("utf-8"))
    else:
        sys.stdout.buffer.write(serialized.encode("utf-8"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
