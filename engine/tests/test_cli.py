"""Tests for `agentic_sdlc_langgraph.cli` (`agentic-sdlc-lg`).

Two test styles are mixed deliberately:

- In-process `cli.main([...])` calls for most of the coverage (fast: no
  subprocess/interpreter-startup overhead).
- Real `subprocess.run([...])` invocations of the *actual installed
  console script* (`agentic-sdlc-lg`, wired via `pyproject.toml`'s
  `[project.scripts]`) for `test_console_script_entry_point_is_installed`
  and, most importantly, `test_plan_then_resume_across_separate_processes`
  -- the test that proves this phase's central claim: a full task can be
  planned in one OS process and resumed in a genuinely separate one, with
  the on-disk sqlite checkpointer + `graph-config.json` (not any shared
  Python object) carrying the state across the boundary. See that test's
  docstring below for exactly what it proves and how.

All subprocess invocations set `AGENTIC_SDLC_LANGGRAPH_FAKE_MODEL=1` in
the child's environment so no network call or `ANTHROPIC_API_KEY` is ever
required.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_sdlc_langgraph import cli

TASK_TEXT = "Define and review a small internal order-processing API architecture and service"

APPROVAL = {
    "status": "approved",
    "approver": {"id": "product_owner", "role": "Product Owner", "kind": "human"},
    "evidence_refs": [{
        "evidence_id": "test-evidence",
        "uri": "test-evidence:manual",
        "hash_algorithm": "sha256",
        "hash": "0" * 64,
        "classification": "internal",
    }],
}


@pytest.fixture(autouse=True)
def _fake_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTIC_SDLC_LANGGRAPH_FAKE_MODEL", "1")


def _run_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_plan_prints_interrupt_and_writes_graph_config(tmp_path: Path, capsys):
    code, out, _err = _run_cli(
        ["plan", "--root", str(tmp_path), "--task-id", "t1", "--task", TASK_TEXT], capsys
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "interrupted"
    assert payload["interrupt"]["gate_id"] == "G1"
    assert (tmp_path / ".agentic-sdlc" / "runs" / "t1" / "graph-config.json").is_file()


def test_plan_twice_is_a_noop_second_time(tmp_path: Path, capsys):
    _run_cli(["plan", "--root", str(tmp_path), "--task-id", "t1", "--task", TASK_TEXT], capsys)
    code, out, _err = _run_cli(
        ["plan", "--root", str(tmp_path), "--task-id", "t1", "--task", TASK_TEXT], capsys
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "already-planned"


def test_plan_rejects_conflicting_task_text(tmp_path: Path, capsys):
    _run_cli(["plan", "--root", str(tmp_path), "--task-id", "t1", "--task", TASK_TEXT], capsys)
    code, _out, err = _run_cli(
        ["plan", "--root", str(tmp_path), "--task-id", "t1", "--task", "a different task"], capsys
    )
    assert code == 1
    assert "different task text" in err


def test_plan_links_gitlab_issues_and_export_reflects_them(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch):
    # fetch_gitlab_issue(project_path, issue_iid) returns {"iid": issue_iid,
    # ...} using the *requested* iid (parsed from the --*-gitlab-issue
    # reference string), not whatever "iid" happens to be in the mocked
    # response body -- exactly matching a real `glab api
    # projects/:id/issues/:iid` call, where the requested iid and the
    # response's iid are always the same value anyway. So one shared mock
    # file is enough to distinguish the two links; only the reference
    # strings' iid parts (42 vs 43) need to differ.
    mock_issue = {"iid": 0, "title": "Support SSO login", "state": "opened", "web_url": None, "updated_at": None}
    mock_file = tmp_path / "issue.json"
    mock_file.write_text(json.dumps(mock_issue), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE", str(mock_file))

    code, out, _err = _run_cli(
        [
            "plan", "--root", str(tmp_path), "--task-id", "t1", "--task", TASK_TEXT,
            "--intent-gitlab-issue", "group/project#42",
            "--requirements-gitlab-issue", "group/project#43",
        ],
        capsys,
    )
    assert code == 0, _err
    assert json.loads(out)["status"] == "interrupted"

    code, out, _err = _run_cli(["export", "--root", str(tmp_path), "--task-id", "t1"], capsys)
    assert code == 0
    record = json.loads(out)
    assert record["intent_record_id"] == "gitlab-issue:group/project:issues/42"
    assert record["requirements_baseline_id"] == "gitlab-issue:group/project:issues/43"


def test_plan_rejects_malformed_gitlab_issue_reference(tmp_path: Path, capsys):
    code, _out, err = _run_cli(
        [
            "plan", "--root", str(tmp_path), "--task-id", "t1", "--task", TASK_TEXT,
            "--intent-gitlab-issue", "not-a-valid-reference",
        ],
        capsys,
    )
    assert code == 1
    assert "project-path" in err


def test_status_on_unknown_task_fails_cleanly(tmp_path: Path, capsys):
    code, _out, err = _run_cli(["status", "--root", str(tmp_path), "--task-id", "nope"], capsys)
    assert code == 1
    assert "graph-config.json" in err


def test_full_g1_g3_walkthrough_plan_resume_status_export_validate(tmp_path: Path, capsys):
    root = str(tmp_path)

    code, out, _err = _run_cli(["plan", "--root", root, "--task-id", "t1", "--task", TASK_TEXT], capsys)
    assert code == 0
    assert json.loads(out)["interrupt"]["gate_id"] == "G1"

    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(APPROVAL), encoding="utf-8")

    for expected_next in ("G2", "G3"):
        code, out, _err = _run_cli(
            ["resume", "--root", root, "--task-id", "t1", "--decision", str(decision_path)], capsys
        )
        assert code == 0
        assert json.loads(out)["interrupt"]["gate_id"] == expected_next

    code, out, _err = _run_cli(
        ["resume", "--root", root, "--task-id", "t1", "--decision", str(decision_path)], capsys
    )
    assert code == 0
    assert json.loads(out)["status"] == "complete"

    code, out, _err = _run_cli(["status", "--root", root, "--task-id", "t1"], capsys)
    assert code == 0
    status = json.loads(out)
    assert status["interrupted"] is False
    assert [g["status"] for g in status["gates"]] == ["approved", "approved", "approved"]

    code, out, _err = _run_cli(["export", "--root", root, "--task-id", "t1"], capsys)
    assert code == 0
    record = json.loads(out)
    assert record["task_id"] == "t1"
    assert len(record["lifecycle_gates"]) == 10

    # Authorities were never assigned (the CLI has no --authority flag by
    # design -- see task report), so every gate's authority requirement
    # resolves "unknown" -> validate must report a *blocker*, not a hard
    # error: structurally valid, but not ready without a human decision.
    code, out, _err = _run_cli(["validate", "--root", root, "--task-id", "t1"], capsys)
    assert code == 2
    result = json.loads(out)
    assert result["valid"] is True
    assert result["ready"] is False
    assert result["errors"] == []
    assert result["blockers"]


def test_validate_is_clean_immediately_after_plan(tmp_path: Path, capsys):
    """Nothing has been approved yet, so no gate's `status == "approved"`
    branch of `validate_run_record` runs at all -- a freshly-planned,
    untouched task must validate as fully clean (code 0)."""
    root = str(tmp_path)
    _run_cli(["plan", "--root", root, "--task-id", "t1", "--task", TASK_TEXT], capsys)
    code, out, _err = _run_cli(["validate", "--root", root, "--task-id", "t1"], capsys)
    assert code == 0
    result = json.loads(out)
    assert result == {"valid": True, "ready": True, "errors": [], "blockers": []}


def test_invalidate_then_reenter_redispatches_the_gate(tmp_path: Path, capsys):
    root = str(tmp_path)
    _run_cli(["plan", "--root", root, "--task-id", "t1", "--task", TASK_TEXT], capsys)

    code, out, _err = _run_cli(
        [
            "invalidate",
            "--root", root,
            "--task-id", "t1",
            "--earliest-gate", "G1",
            "--reason", "requirements changed",
            "--actor", "tester",
        ],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["status"] == "invalidated"
    assert payload["record"]["invalidated_gate_ids"] == ["G1", "G2", "G3"]

    code, out, _err = _run_cli(["status", "--root", root, "--task-id", "t1"], capsys)
    status = json.loads(out)
    assert [g["status"] for g in status["gates"]] == ["invalidated", "invalidated", "invalidated"]

    code, out, _err = _run_cli(
        [
            "reenter",
            "--root", root,
            "--task-id", "t1",
            "--earliest-gate", "G1",
            "--reason", "resubmitting",
            "--actor", "tester",
        ],
        capsys,
    )
    assert code == 0
    # Two JSON documents are printed by `reenter` (the reentry record, then
    # the re-dispatch invoke result) -- parse them as a JSON stream.
    decoder = json.JSONDecoder()
    text = out.strip()
    first, idx = decoder.raw_decode(text)
    second, _ = decoder.raw_decode(text[idx:].strip())
    assert first["status"] == "reentered"
    assert second["status"] == "interrupted"
    assert second["interrupt"]["gate_id"] == "G1"  # re-dispatched, not just reset


def test_invalidate_rejects_gate_outside_sequence(tmp_path: Path, capsys):
    root = str(tmp_path)
    _run_cli(["plan", "--root", root, "--task-id", "t1", "--task", TASK_TEXT], capsys)
    code, _out, err = _run_cli(
        [
            "invalidate",
            "--root", root,
            "--task-id", "t1",
            "--earliest-gate", "G7",
            "--reason", "x",
            "--actor", "y",
        ],
        capsys,
    )
    assert code == 1
    assert "G7" in err


def test_status_reports_pending_interrupt_after_invalidate(tmp_path: Path, capsys):
    """K1 fix: `invalidate` calls `graph.update_state(...)`, which empties
    `snapshot.interrupts` while the graph stays genuinely suspended at
    `human_approval_G1`. `status` must still report that."""
    root = str(tmp_path)
    _run_cli(["plan", "--root", root, "--task-id", "t1", "--task", TASK_TEXT], capsys)

    _run_cli(
        [
            "invalidate",
            "--root", root,
            "--task-id", "t1",
            "--earliest-gate", "G1",
            "--reason", "requirements changed",
            "--actor", "tester",
        ],
        capsys,
    )

    code, out, _err = _run_cli(["status", "--root", root, "--task-id", "t1"], capsys)
    assert code == 0
    status = json.loads(out)
    assert status["interrupted"] is True
    assert status["interrupt"] is None
    assert status["interrupt_payload_unavailable"] is True
    assert status["pending_interrupt_node"] == "human_approval_G1"


def test_resume_decision_from_stdin(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch):
    root = str(tmp_path)
    _run_cli(["plan", "--root", root, "--task-id", "t1", "--task", TASK_TEXT], capsys)

    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(APPROVAL)))
    code, out, _err = _run_cli(["resume", "--root", root, "--task-id", "t1", "--decision", "-"], capsys)
    assert code == 0
    assert json.loads(out)["interrupt"]["gate_id"] == "G2"


# --------------------------------------------------------------------------
# Real subprocess tests
# --------------------------------------------------------------------------


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AGENTIC_SDLC_LANGGRAPH_FAKE_MODEL"] = "1"
    return env


def test_console_script_entry_point_is_installed(tmp_path: Path):
    """Proves the packaging actually works: the `agentic-sdlc-lg` console
    script from `pyproject.toml`'s `[project.scripts]` is installed and
    runnable via `uv run`, not just importable as a Python module."""
    result = subprocess.run(
        ["uv", "run", "agentic-sdlc-lg", "plan", "--root", str(tmp_path), "--task-id", "t1", "--task", TASK_TEXT],
        cwd=Path(__file__).resolve().parents[1],
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["interrupt"]["gate_id"] == "G1"


def test_plan_then_resume_across_separate_processes(tmp_path: Path):
    """The single most important test in this phase.

    Runs `plan` as one real OS subprocess, then `resume` (twice more, to
    walk G1 -> G2 -> G3) as three further, genuinely separate subprocess
    invocations -- no LangGraph object, no Python variable, nothing at all
    is held in memory between these calls. Each subprocess is a brand new
    Python interpreter that only shares the filesystem with the others
    (the `--root` directory: `graph-config.json` plus the on-disk
    `state.db` sqlite file).

    This proves the phase's core claim: a full multi-gate run can complete
    via the CLI alone, across separate process invocations, with zero
    chat CLI (Claude Code / Codex CLI) involvement and no single
    long-lived process required. If graph reconnection were broken --
    wrong gate topology, lost checkpoint, mismatched thread_id -- this
    would fail with either a missing/wrong interrupt or an exception, not
    silently pass.
    """
    root = tmp_path
    task_id = "cross-process-task"
    module_invocation = [sys.executable, "-m", "agentic_sdlc_langgraph.cli"]
    cwd = Path(__file__).resolve().parents[1]
    env = _subprocess_env()

    def run(argv: list[str]) -> dict:
        result = subprocess.run(
            module_invocation + argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"argv={argv}\nstdout={result.stdout}\nstderr={result.stderr}"
        return json.loads(result.stdout)

    # Process 1: plan.
    payload = run(["plan", "--root", str(root), "--task-id", task_id, "--task", TASK_TEXT])
    assert payload["status"] == "interrupted"
    assert payload["interrupt"]["gate_id"] == "G1"

    db_path = root / ".agentic-sdlc" / "state.db"
    config_path = root / ".agentic-sdlc" / "runs" / task_id / "graph-config.json"
    assert db_path.is_file(), "the persistent sqlite checkpointer file must exist after plan"
    assert config_path.is_file(), "graph-config.json must exist after plan"

    decision_path = root / "decision.json"
    decision_path.write_text(json.dumps(APPROVAL), encoding="utf-8")

    # Process 2: resume G1 -> interrupts at G2.
    payload = run(["resume", "--root", str(root), "--task-id", task_id, "--decision", str(decision_path)])
    assert payload["status"] == "interrupted"
    assert payload["interrupt"]["gate_id"] == "G2"

    # Process 3: resume G2 -> interrupts at G3.
    payload = run(["resume", "--root", str(root), "--task-id", task_id, "--decision", str(decision_path)])
    assert payload["status"] == "interrupted"
    assert payload["interrupt"]["gate_id"] == "G3"

    # Process 4: resume G3 -> run complete.
    payload = run(["resume", "--root", str(root), "--task-id", task_id, "--decision", str(decision_path)])
    assert payload["status"] == "complete"

    # Process 5: an entirely separate `status` invocation confirms the
    # final state was durably persisted, not just returned by the last
    # `resume` call's own in-memory result.
    payload = run(["status", "--root", str(root), "--task-id", task_id])
    assert payload["interrupted"] is False
    assert [g["status"] for g in payload["gates"]] == ["approved", "approved", "approved"]

    # Process 6: export, likewise from scratch.
    payload = run(["export", "--root", str(root), "--task-id", task_id])
    assert payload["task_id"] == task_id
    assert all(
        gate["status"] == "approved"
        for gate in payload["lifecycle_gates"]
        if gate["gate_id"] in {"G1", "G2", "G3"}
    )
