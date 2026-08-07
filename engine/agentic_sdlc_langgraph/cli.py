"""Standalone CLI entrypoint: `agentic-sdlc-lg <subcommand> ...`.

Each invocation is its own process. Every subcommand below (other than
`plan`, which may create a new task) reconnects to an already-planned
task's compiled graph via `runtime.build_graph_for_task` -- see
`runtime.py`'s module docstring for why that reconnection step exists and
how `graph-config.json` makes it deterministic.

Subcommand shape is ported in *spirit* from the legacy CLI's
`plan`/`detect`/`validate`/`status`/`invalidate`/`reenter`/
`approve-from-github` (`agentic_sdlc.py`), not its exact argument surface:
this is a new graph-shaped runtime, not a drop-in replacement.

Exit-code convention for `validate` mirrors the legacy CLI's
`validate_repository` exactly (`agentic_sdlc.py`'s `validate_repository`,
tail end): `0` valid and ready (no errors, no blockers), `2` structurally
valid but blocked on an unresolved decision, `1` a real structural/semantic
defect. This matters for CI integration (a build step can treat `0` as
"proceed", `2` as "needs a human decision, not a build failure", `1` as
"fix the run record").
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from langgraph.types import Command

from . import requirement_issues, runtime
from .contracts import load_lifecycle_gates
from .export import export_run_record
from .gitlab_issue import resolve_issue_reference
from .reentry import invalidate_gates, reenter_gate
from .validate import validate_run_record


def _parse_ignored_gates(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_decision(value: str) -> Any:
    """Parse `--decision`: either a path to a JSON file, or `-` to read a
    JSON document from stdin."""
    text = sys.stdin.read() if value == "-" else Path(value).read_text(encoding="utf-8")
    return json.loads(text)


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2))


def _error(message: str) -> None:
    print(json.dumps({"error": message}, indent=2), file=sys.stderr)


def _rebuild(root: Path, task_id: str, **kwargs: Any):
    """Common `build_graph_for_task` call + error handling for every
    subcommand except `plan` (which needs bespoke first-time handling).
    Returns `None` (after printing an error to stderr) on failure so
    callers can `return 1` immediately."""
    try:
        return runtime.build_graph_for_task(root, task_id, **kwargs)
    except runtime.GraphConfigError as exc:
        _error(str(exc))
        return None


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    ignored_gate_ids = _parse_ignored_gates(args.ignored_gates)
    already_planned = runtime.task_exists(root, args.task_id)

    built = _rebuild(
        root,
        args.task_id,
        task_text=args.task,
        profile_id=args.profile,
        provider_manifest=args.provider,
        ignored_gate_ids=ignored_gate_ids,
    )
    if built is None:
        return 1
    graph, config, metadata = built

    if already_planned:
        _print(
            {
                "status": "already-planned",
                "message": f"task {args.task_id!r} was already planned; use resume/status instead",
                "gate_sequence": metadata.gate_sequence_ids,
            }
        )
        return 0

    try:
        intent_record_id = resolve_issue_reference(args.intent_gitlab_issue)
        requirements_baseline_id = resolve_issue_reference(args.requirements_gitlab_issue)
    except ValueError as exc:
        _error(str(exc))
        return 1
    result = graph.invoke(
        runtime.initial_state(
            args.task_id,
            args.task,
            intent_record_id=intent_record_id,
            requirements_baseline_id=requirements_baseline_id,
        ),
        config=config,
    )
    _print(runtime.invoke_result_payload(result))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    root = Path(args.root)
    built = _rebuild(root, args.task_id)
    if built is None:
        return 1
    graph, config, _metadata = built

    decision = _load_decision(args.decision)
    result = graph.invoke(Command(resume=decision), config=config)
    _print(runtime.invoke_result_payload(result))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root)
    built = _rebuild(root, args.task_id)
    if built is None:
        return 1
    graph, config, metadata = built

    _print(runtime.status_summary(graph, config, metadata))
    return 0


def cmd_invalidate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    built = _rebuild(root, args.task_id)
    if built is None:
        return 1
    graph, config, metadata = built

    if args.earliest_gate not in metadata.gate_sequence_ids:
        _error(
            f"gate {args.earliest_gate!r} is not part of task {args.task_id!r}'s derived "
            f"gate sequence {metadata.gate_sequence_ids}"
        )
        return 1

    record = invalidate_gates(
        graph, config, args.earliest_gate, args.reason, args.actor, metadata.gate_sequence_ids
    )
    _print({"status": "invalidated", "record": record})
    return 0


def cmd_reenter(args: argparse.Namespace) -> int:
    root = Path(args.root)
    built = _rebuild(root, args.task_id)
    if built is None:
        return 1
    graph, config, metadata = built

    if args.earliest_gate not in metadata.gate_sequence_ids:
        _error(
            f"gate {args.earliest_gate!r} is not part of task {args.task_id!r}'s derived "
            f"gate sequence {metadata.gate_sequence_ids}"
        )
        return 1

    record = reenter_gate(
        graph, config, args.earliest_gate, args.reason, args.actor, metadata.gate_sequence_ids
    )
    _print({"status": "reentered", "record": record})

    # reenter_gate redirects the checkpoint's position but does not itself
    # resume execution (see reentry.py's docstring) -- actually re-dispatch
    # the reentered gate's agents here so `reenter` is a complete,
    # observable operation from the CLI, not just a state patch.
    result = graph.invoke(None, config=config)
    _print(runtime.invoke_result_payload(result))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    root = Path(args.root)
    built = _rebuild(root, args.task_id)
    if built is None:
        return 1
    graph, config, metadata = built

    snapshot = graph.get_state(config)
    record = export_run_record(
        snapshot.values,
        sequence_gate_ids=metadata.gate_sequence_ids,
        ignored_gate_ids=metadata.ignored_gate_ids,
    )
    text = json.dumps(record, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    built = _rebuild(root, args.task_id)
    if built is None:
        return 1
    graph, config, metadata = built

    snapshot = graph.get_state(config)
    record = export_run_record(
        snapshot.values,
        sequence_gate_ids=metadata.gate_sequence_ids,
        ignored_gate_ids=metadata.ignored_gate_ids,
    )
    schema = json.loads((runtime.CONTRACTS_DIR / "run-record.schema.json").read_text(encoding="utf-8"))
    all_gates = load_lifecycle_gates(runtime.CONTRACTS_DIR / "lifecycle-gates.json")
    gate_contracts = {gate["id"]: gate for gate in all_gates}

    code, messages = validate_run_record(record, schema, gate_contracts=gate_contracts)
    _print(
        {
            "valid": code != 1,
            "ready": code == 0,
            "errors": messages if code == 1 else [],
            "blockers": messages if code == 2 else [],
        }
    )
    return code


def cmd_create_requirement_issues(args: argparse.Namespace) -> int:
    """GitLab-only Stage A requirement-item -> issue publisher. Reuses
    `build_graph_for_task` only to read live gate/eligibility state (never
    to dispatch anything) -- see `requirement_issues.run`'s docstring for
    why the live-state read is a callback rather than an import."""
    root = Path(args.root)
    built = _rebuild(root, args.task_id)
    if built is None:
        return 1
    graph, config, metadata = built
    gate_id = "G2"

    # Fail closed on operator misuse: a task whose derived gate sequence
    # never included G2 at all (e.g. a route that skipped it) has no
    # meaningful "publish for G2" operation -- without this check, a
    # missing `lifecycle_gates["G2"]` entry would fall through to the
    # same `gate_status: "pending"` default used for "in-sequence but not
    # yet reached", silently treating an out-of-scope gate as eligible.
    if gate_id not in metadata.gate_sequence_ids:
        _error(
            f"gate {gate_id!r} is not part of task {args.task_id!r}'s derived gate sequence "
            f"{metadata.gate_sequence_ids} -- create-requirement-issues has nothing to publish for"
        )
        return 1

    def get_eligibility() -> requirement_issues.Eligibility:
        snapshot = graph.get_state(config)
        values = snapshot.values or {}
        gate = values.get("lifecycle_gates", {}).get(gate_id)
        return requirement_issues.Eligibility(
            run_halted=bool(values.get("run_halted", False)),
            required_reentry_gate=gate.get("required_reentry_gate") if gate else None,
            gate_status=gate.get("status") if gate else "pending",
            re_entry_count=len(values.get("re_entry_history", [])),
            classification=values.get("classification"),
        )

    try:
        result = requirement_issues.run(
            root=root,
            task_id=args.task_id,
            project=args.project,
            items_source=args.items,
            as_bot=args.as_bot,
            apply=args.apply,
            plan_digest=args.plan_digest,
            allow_classification=args.allow_classification,
            max_items=args.max_items,
            break_lock=args.break_lock,
            i_know_this_is_mocked=args.i_know_this_is_mocked,
            get_eligibility=get_eligibility,
        )
    except requirement_issues.RequirementIssuesBlocked as exc:
        _error(str(exc))
        return 2
    except requirement_issues.RequirementIssuesError as exc:
        _error(str(exc))
        return 1

    _print(result)
    return 0


def cmd_list_requirement_issues(args: argparse.Namespace) -> int:
    """Reads the sidecar ledger file directly -- must NOT rebuild the
    graph / call `build_graph_for_task` (the ledger, not the checkpoint,
    is what this command reports on)."""
    root = Path(args.root)
    ledger = requirement_issues.read_ledger(root, args.task_id)
    _print(ledger)
    return 0


# --------------------------------------------------------------------------
# argparse wiring
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-sdlc-lg")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan", help="Plan a new task: derive its gate sequence and run it to the first interrupt.")
    plan_p.add_argument("--root", required=True)
    plan_p.add_argument("--task-id", required=True)
    plan_p.add_argument("--task", required=True)
    plan_p.add_argument("--profile", default="generic")
    plan_p.add_argument("--ignored-gates", default="", help="Comma-separated gate ids, e.g. G4,G5")
    plan_p.add_argument("--provider", default=None, help="Path to a provider manifest (provider.json)")
    plan_p.add_argument(
        "--intent-gitlab-issue",
        default=None,
        help="Link a GitLab issue as G1 Intent's source, in <project-path>#<iid> form (e.g. group/project#42)",
    )
    plan_p.add_argument(
        "--requirements-gitlab-issue",
        default=None,
        help="Link a GitLab issue as G2 Requirements Baseline's source, in <project-path>#<iid> form",
    )
    plan_p.set_defaults(func=cmd_plan)

    resume_p = sub.add_parser("resume", help="Resume an interrupted task with a decision.")
    resume_p.add_argument("--root", required=True)
    resume_p.add_argument("--task-id", required=True)
    resume_p.add_argument("--decision", required=True, help="Path to a JSON file, or '-' for stdin")
    resume_p.set_defaults(func=cmd_resume)

    status_p = sub.add_parser("status", help="Print a task's current gate/interrupt status.")
    status_p.add_argument("--root", required=True)
    status_p.add_argument("--task-id", required=True)
    status_p.set_defaults(func=cmd_status)

    invalidate_p = sub.add_parser("invalidate", help="Invalidate a gate and every gate after it.")
    invalidate_p.add_argument("--root", required=True)
    invalidate_p.add_argument("--task-id", required=True)
    invalidate_p.add_argument("--earliest-gate", required=True)
    invalidate_p.add_argument("--reason", required=True)
    invalidate_p.add_argument("--actor", required=True)
    invalidate_p.set_defaults(func=cmd_invalidate)

    reenter_p = sub.add_parser("reenter", help="Reset a gate (and downstream gates) and re-dispatch it.")
    reenter_p.add_argument("--root", required=True)
    reenter_p.add_argument("--task-id", required=True)
    reenter_p.add_argument("--earliest-gate", required=True)
    reenter_p.add_argument("--reason", required=True)
    reenter_p.add_argument("--actor", required=True)
    reenter_p.set_defaults(func=cmd_reenter)

    export_p = sub.add_parser("export", help="Export the run record (run-record.schema.json shape).")
    export_p.add_argument("--root", required=True)
    export_p.add_argument("--task-id", required=True)
    export_p.add_argument("--output", default=None, help="Write to this file instead of stdout")
    export_p.set_defaults(func=cmd_export)

    validate_p = sub.add_parser("validate", help="Export + validate the run record; exit 0/1/2.")
    validate_p.add_argument("--root", required=True)
    validate_p.add_argument("--task-id", required=True)
    validate_p.set_defaults(func=cmd_validate)

    create_issues_p = sub.add_parser(
        "create-requirement-issues",
        help="Publish a G2 Requirements Baseline item list as GitLab issues (Stage A, GitLab-only).",
    )
    create_issues_p.add_argument("--root", required=True)
    create_issues_p.add_argument("--task-id", required=True)
    create_issues_p.add_argument("--project", required=True, help="GitLab project path, e.g. group/project")
    create_issues_p.add_argument("--items", required=True, help="Path to the items JSON file, or '-' for stdin")
    create_issues_p.add_argument(
        "--as-bot", required=True, help="Required GitLab bot/machine username; verified via `glab api user`"
    )
    mode_group = create_issues_p.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", dest="apply", action="store_false", help="Default: print the plan digest only")
    mode_group.add_argument("--apply", dest="apply", action="store_true", help="Actually create/reuse issues")
    create_issues_p.set_defaults(apply=False)
    create_issues_p.add_argument("--plan-digest", default=None, help="Required with --apply (from a prior --dry-run)")
    create_issues_p.add_argument(
        "--allow-classification", default=None,
        help="Must exactly match the task's state classification -- no default, no ordering/threshold logic",
    )
    create_issues_p.add_argument("--max-items", type=int, default=requirement_issues.DEFAULT_MAX_ITEMS)
    create_issues_p.add_argument("--break-lock", action="store_true", help="Explicitly override a held lock file")
    create_issues_p.add_argument(
        "--i-know-this-is-mocked", action="store_true",
        help="Required alongside --apply whenever AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE is set",
    )
    create_issues_p.set_defaults(func=cmd_create_requirement_issues)

    list_issues_p = sub.add_parser(
        "list-requirement-issues", help="Print the requirement-issues sidecar ledger for a task."
    )
    list_issues_p.add_argument("--root", required=True)
    list_issues_p.add_argument("--task-id", required=True)
    list_issues_p.set_defaults(func=cmd_list_requirement_issues)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def run() -> None:
    """Console-script entry point (see `pyproject.toml`'s
    `[project.scripts]`)."""
    sys.exit(main())


if __name__ == "__main__":
    run()
