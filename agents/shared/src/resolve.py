#!/usr/bin/env python3
"""Resolve the effective content of an agents/shared/<filename> default.

A project may extend or, for structured files, override this repository's
shared defaults by placing a same-named file at .agents/shared/<filename> in
its own tree (found by walking up from the current directory to the nearest
.git boundary, the same convention agents/knowledge-store/src/config.py uses
for its project-local config.json). See agents/shared/README.md for the
precedence order and the merge rule for each file type.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SHARED_DEFAULTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_OVERLAY_RELATIVE_DIR = Path(".agents") / "shared"
MAXIMUM_WALK_DEPTH = 64

# The only two sentinel values that make a narrowing check meaningful without
# hand-ranking every bespoke autonomy string in agent-autonomy.yaml: the
# fully permissive value and the fully forbidden value. An overlay may not
# loosen a restricted default (anything other than "allowed") to "allowed",
# and may not loosen a "never" default to anything else.
_UNRESTRICTED = "allowed"
_MAXIMUM_RESTRICTION = "never"
_AUTONOMY_FILENAME = "agent-autonomy.yaml"
# The autonomy contract itself, not a per-project dial; an overlay may not
# touch these two keys at all.
_AUTONOMY_FIXED_KEYS = {"policy_version", "default_rule"}


class OverlayError(ValueError):
    """A project-local overlay is malformed or violates a merge rule."""


def find_project_overlay(filename: str, start: Path | None = None) -> Path | None:
    """Walk upward from `start` for a project-local .agents/shared/<filename>.

    Stops at the first directory containing .git (the project boundary) or
    after MAXIMUM_WALK_DEPTH levels if no .git is found, so an overlay above
    the project root is never picked up.
    """
    current = (start or Path.cwd()).resolve()
    for _ in range(MAXIMUM_WALK_DEPTH):
        candidate = current / PROJECT_OVERLAY_RELATIVE_DIR / filename
        if candidate.is_file():
            return candidate
        if (current / ".git").exists():
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _require_yaml():
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError(
            "PyYAML is required to resolve a YAML shared config; see "
            "agents/shared/requirements-validation.txt"
        ) from error
    return yaml


def _load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        loaded = json.loads(text)
    else:
        loaded = _require_yaml().safe_load(text)
    if not isinstance(loaded, dict):
        raise OverlayError(f"{path}: root must be a mapping")
    return loaded


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `overlay` over `base`; overlay wins per key.

    Mirrors agents/knowledge-store/src/config.py's _merge: only dict values
    recurse, everything else (including lists) is replaced wholesale by the
    overlay's value.
    """
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _autonomy_leaf_paths(node: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    for key, value in node.items():
        path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, dict):
            paths.extend(_autonomy_leaf_paths(value, path))
        else:
            paths.append((path, value))
    return paths


def _check_autonomy_overlay(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    """Enforce that an agent-autonomy.yaml overlay only narrows autonomy.

    Raises OverlayError if the overlay touches the fixed policy_version /
    default_rule keys, references a category or key the default doesn't
    define, loosens a "never" default, or loosens any other restricted
    default to "allowed".
    """
    for fixed_key in _AUTONOMY_FIXED_KEYS:
        if fixed_key in overlay:
            raise OverlayError(
                f"agent-autonomy.yaml overlay may not set {fixed_key!r}; "
                "it is the fixed autonomy contract, not a per-project dial"
            )
    base_values = dict(_autonomy_leaf_paths(base))
    for path, overlay_value in _autonomy_leaf_paths(overlay):
        if path not in base_values:
            raise OverlayError(
                f"agent-autonomy.yaml overlay references undefined key {path!r}"
            )
        default_value = base_values[path]
        if default_value == overlay_value:
            continue
        if default_value == _MAXIMUM_RESTRICTION:
            raise OverlayError(f"{path}: overlay may not loosen a 'never' default")
        if default_value != _UNRESTRICTED and overlay_value == _UNRESTRICTED:
            raise OverlayError(f"{path}: overlay may not loosen {default_value!r} to 'allowed'")


def resolve_shared_config(filename: str, start: Path | None = None) -> Any:
    """Return the effective content for agents/shared/<filename>.

    Structured files (.yaml/.yml/.json) are deep-merged with the project
    overlay winning per key; agent-autonomy.yaml additionally rejects any
    overlay that loosens a restriction. Markdown files are returned as the
    base text with the overlay appended as a project addendum — an overlay
    never replaces prose, it only adds to it.

    Returns a dict for structured files, a str for Markdown.
    """
    default_path = SHARED_DEFAULTS_DIR / filename
    if not default_path.is_file():
        raise FileNotFoundError(f"No such shared default: {default_path}")
    overlay_path = find_project_overlay(filename, start)

    suffix = default_path.suffix.lower()
    if suffix == ".md":
        base_text = default_path.read_text(encoding="utf-8")
        if overlay_path is None:
            return base_text
        addendum = overlay_path.read_text(encoding="utf-8")
        return f"{base_text}\n## Project addendum ({overlay_path})\n\n{addendum}"

    base = _load_structured(default_path)
    if overlay_path is None:
        return base
    overlay = _load_structured(overlay_path)
    if filename == _AUTONOMY_FILENAME:
        _check_autonomy_overlay(base, overlay)
    return deep_merge(base, overlay)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resolve.py", description="Resolve an effective agents/shared/ config for the current project"
    )
    parser.add_argument("filename", help="Shared default filename, e.g. agent-autonomy.yaml")
    parser.add_argument("--project", type=Path, help="Directory to resolve overlays from (default: cwd)")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        resolved = resolve_shared_config(arguments.filename, start=arguments.project)
    except (FileNotFoundError, OverlayError, RuntimeError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    if isinstance(resolved, str):
        sys.stdout.write(resolved if resolved.endswith("\n") else resolved + "\n")
    elif arguments.filename.lower().endswith(".json"):
        sys.stdout.write(json.dumps(resolved, indent=2) + "\n")
    else:
        sys.stdout.write(_require_yaml().safe_dump(resolved, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
