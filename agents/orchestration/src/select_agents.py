#!/usr/bin/env python3
"""Command-line entry point for deterministic local agent selection."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

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
    parser.add_argument("--files", action="append", help="Changed path or comma-separated paths; repeatable")
    parser.add_argument("--base", help="Git base ref used with <base>...HEAD")
    parser.add_argument("--task-id", help="Stable caller-supplied task identifier")
    parser.add_argument("--classification", help="Authorized knowledge classification")
    parser.add_argument("--source", help="Optional knowledge-store source filter")
    parser.add_argument("--top", help="Maximum knowledge results per agent", default="5")
    parser.add_argument("--output", help="Write the JSON plan to this path")
    return parser


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def discover_changed_files(base: str | None) -> dict[str, object]:
    if base:
        files = [line for line in _run_git(["diff", "--name-only", f"{base}...HEAD"]).splitlines() if line]
        return {"source": f"git-diff:{base}...HEAD", "files": files}
    lines = [line for line in _run_git(["status", "--short"]).splitlines() if line]
    files = []
    for line in lines:
        value = line[3:].strip()
        files.append(value.rsplit(" -> ", 1)[-1])
    return {"source": "git-status", "files": files}


def explicit_files(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    files = []
    for value in values:
        files.extend(entry.strip() for entry in value.split(",") if entry.strip())
    return list(dict.fromkeys(files))


def main(argv: list[str] | None = None) -> int:
    options = _parser().parse_args(argv)
    supplied_files = explicit_files(options.files)
    changes = (
        {"source": "explicit", "files": supplied_files}
        if supplied_files is not None
        else discover_changed_files(options.base)
    )
    config = load_routing(ORCHESTRATION_ROOT / "routing.yaml")
    catalog = load_catalog(AGENTS_ROOT / "catalog.yaml")
    plan = build_dispatch_plan(
        config,
        catalog,
        {
            "task": options.task,
            "task_id": options.task_id,
            "base": options.base,
            "changed_files": [str(file_name).replace("\\", "/") for file_name in changes["files"]],
            "changed_file_source": changes["source"],
            "classification": options.classification,
            "source": options.source,
            "top": options.top,
        },
    )
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
