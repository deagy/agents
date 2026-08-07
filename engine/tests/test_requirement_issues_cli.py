"""Integration tests for `create-requirement-issues` / `list-requirement-
issues` through `cli.py` (`agentic-sdlc-lg`), covering the spec's test
plan: zero-network, label-reuse idempotency, sanitization bypass corpus,
post-creation verification, preflight, concurrency/durability, plan
digest, repo-health, and the non-interference invariant.

All GitLab calls are mocked via `AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE`
(see `gitlab_issue.py`'s docstring for the mock-file shape) -- no
network, no `glab` binary required.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from agentic_sdlc_langgraph import cli, requirement_issues, runtime
from agentic_sdlc_langgraph.export import export_run_record
from agentic_sdlc_langgraph.reentry import invalidate_gates

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
BOT = "svc-agentic-sdlc"

ITEMS_ONE = {
    "schema_version": 1,
    "gate_id": "G2",
    "items": [{"key": "REQ-001", "title": "Support SSO login", "description": "As a user I want SSO login."}],
}


@pytest.fixture(autouse=True)
def _fake_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTIC_SDLC_LANGGRAPH_FAKE_MODEL", "1")


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _plan(root: Path, task_id: str, capsys) -> None:
    code, _out, err = _run(["plan", "--root", str(root), "--task-id", task_id, "--task", TASK_TEXT], capsys)
    assert code == 0, err


def _write_items(tmp_path: Path, items=ITEMS_ONE, name="items.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def _write_mock(tmp_path: Path, payload: dict, monkeypatch: pytest.MonkeyPatch, name="mock.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE", str(path))
    return path


_MARKER = requirement_issues.compute_marker("t1", "G2", "REQ-001")
_LABEL = requirement_issues.item_label(_MARKER)
_LABEL_KEY = f"agentic-sdlc,{_LABEL}"


def _verify_payload(**overrides) -> dict:
    base = {
        "title": "Support SSO login",
        "state": "opened",
        "labels": ["agentic-sdlc", _LABEL],
        "assignees": [],
        "confidential": False,
        "references": {"full": "group/project#57"},
        "author": {"username": BOT},
        "web_url": "https://gitlab.example.com/group/project/-/issues/57",
    }
    base.update(overrides)
    return base


def _create_mock(**verify_overrides) -> dict:
    return {
        "identity": {"username": BOT},
        "search": {_LABEL_KEY: []},
        "create": {_LABEL_KEY: {"iid": 57}},
        "verify": {"57": _verify_payload(**verify_overrides)},
    }


def _reused_mock(*, iid=57, state="opened", labels=None, author_username=BOT) -> dict:
    """A matched-issue mock for the reuse path: `search` returns the
    minimal shape `search_gitlab_issues_by_labels` yields, and `verify`
    supplies the authoritative `fetch_gitlab_issue_verification` response
    the reuse path now fetches for every matched issue (author check --
    see `_validate_matched_issue`'s neighbor, the reuse-path author
    check in `_process_item_inner`)."""
    search_labels = labels if labels is not None else ["agentic-sdlc", _LABEL]
    return {
        "identity": {"username": BOT},
        "search": {_LABEL_KEY: [{"iid": iid, "state": state, "labels": search_labels}]},
        "create": {},
        "verify": {str(iid): _verify_payload(state=state, labels=search_labels, author={"username": author_username})},
    }


def _dry_run_digest(root: Path, task_id: str, items_path: Path, capsys, classification="internal") -> str:
    code, out, err = _run(
        [
            "create-requirement-issues", "--root", str(root), "--task-id", task_id,
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", classification,
        ],
        capsys,
    )
    assert code == 0, err
    return json.loads(out)["plan_digest"]


def _apply(root: Path, task_id: str, items_path: Path, digest: str, capsys, *, extra: list[str] | None = None):
    argv = [
        "create-requirement-issues", "--root", str(root), "--task-id", task_id,
        "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
        "--allow-classification", "internal", "--apply", "--plan-digest", digest,
        "--i-know-this-is-mocked",
    ]
    if extra:
        argv += extra
    return _run(argv, capsys)


# --------------------------------------------------------------------------
# Zero-network
# --------------------------------------------------------------------------


def test_zero_network_for_full_dry_run_and_apply(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must never be called under the mock env var")

    monkeypatch.setattr(subprocess, "run", _boom)

    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 0, err
    assert json.loads(out)["results"][0]["status"] == "created"


def test_search_query_uses_state_all_not_free_text(tmp_path):
    """Regression pin for the `state=all` requirement: inspect the actual
    (unmocked) query string construction rather than relying only on the
    mocked test double."""
    import inspect

    source = inspect.getsource(__import__("agentic_sdlc_langgraph.gitlab_issue", fromlist=["x"]))
    assert "state=all" in source
    assert "&search=" not in source


# --------------------------------------------------------------------------
# Label reuse / idempotency
# --------------------------------------------------------------------------


def test_create_then_rerun_is_idempotent_zero_creates(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 0, err
    assert json.loads(out)["results"][0]["status"] == "created"

    # Second run: search now finds the created issue -- no create call.
    _write_mock(tmp_path, _reused_mock(), monkeypatch)
    digest2 = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, out, err = _apply(tmp_path, "t1", items_path, digest2, capsys)
    assert code == 0, err
    assert json.loads(out)["results"][0]["status"] == "reused"


def test_reuse_survives_deleted_ledger_forge_is_authoritative(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _reused_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 0, err
    assert json.loads(out)["results"][0]["status"] == "reused"

    ledger_path = tmp_path / ".agentic-sdlc" / "runs" / "t1" / "requirement-issues.json"
    ledger_path.unlink()
    assert not ledger_path.is_file()  # assert the premise: genuinely no local ledger, not just implied

    digest2 = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, out, err = _apply(tmp_path, "t1", items_path, digest2, capsys)
    assert code == 0, err
    result = json.loads(out)["results"][0]
    assert result["status"] == "reused"
    assert result["drift"] == "reused (drift-unknown)"


def test_closed_matched_issue_is_reused_not_recreated(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _reused_mock(state="closed"), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 0, err
    result = json.loads(out)["results"][0]
    assert result["status"] == "reused"
    assert "reused (closed)" in result["drift"]


def test_ambiguous_multiple_matches_aborts(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    mock = {
        "identity": {"username": BOT},
        "search": {
            _LABEL_KEY: [
                {"iid": 57, "state": "opened", "labels": ["agentic-sdlc", _LABEL]},
                {"iid": 58, "state": "opened", "labels": ["agentic-sdlc", _LABEL]},
            ]
        },
        "create": {},
        "verify": {},
    }
    _write_mock(tmp_path, mock, monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, _out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 2
    assert "ambiguous" in err


def test_matched_issue_missing_fixed_label_aborts(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    mock = {
        "identity": {"username": BOT},
        "search": {_LABEL_KEY: [{"iid": 57, "state": "opened", "labels": [_LABEL]}]},
        "create": {},
        "verify": {},
    }
    _write_mock(tmp_path, mock, monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, _out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 2
    assert "missing the" in err


def test_matched_issue_with_foreign_item_label_aborts(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    mock = {
        "identity": {"username": BOT},
        "search": {_LABEL_KEY: [{"iid": 57, "state": "opened", "labels": ["agentic-sdlc", _LABEL, "agentic-sdlc-item-deadbeefdeadbeef"]}]},
        "create": {},
        "verify": {},
    }
    _write_mock(tmp_path, mock, monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, _out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 2
    assert "foreign item label" in err


def test_matched_issue_wrong_author_refuses_reuse(tmp_path, capsys, monkeypatch):
    """The label pair `[FIXED_LABEL, item_label]` is deterministic and
    not secret (see `compute_marker`'s docstring), so a matched issue
    whose author is not the verified bot identity must never be silently
    adopted -- it may be attacker/other-principal-created content that
    never went through this tool's sanitization or creation-time
    controls at all. Mirrors the create-path `author_username` mismatch
    test (`test_post_creation_verification_failure_marks_suspect_and_aborts`),
    but for the reuse path, which previously performed no author check."""
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _reused_mock(author_username="not-the-bot"), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, _out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 2
    assert "author" in err

    ledger = requirement_issues.read_ledger(tmp_path, "t1")
    assert ledger["entries"]["REQ-001"]["status"] == "suspect"


def test_content_drift_reported_on_reuse_never_edits(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    _apply(tmp_path, "t1", items_path, digest, capsys)

    changed_items = copy.deepcopy(ITEMS_ONE)
    changed_items["items"][0]["description"] = "A completely different description now."
    items_path2 = _write_items(tmp_path, changed_items, name="items2.json")
    _write_mock(tmp_path, _reused_mock(), monkeypatch)
    digest2 = _dry_run_digest(tmp_path, "t1", items_path2, capsys)
    code, out, err = _apply(tmp_path, "t1", items_path2, digest2, capsys)
    assert code == 0, err
    result = json.loads(out)["results"][0]
    assert result["status"] == "reused"
    assert result["drift"] == "changed_content"
    assert result["previous_description"] == "As a user I want SSO login."


# --------------------------------------------------------------------------
# Post-creation verification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,expected_substr",
    [
        ({"labels": ["agentic-sdlc"]}, "labels"),
        ({"labels": ["agentic-sdlc", _LABEL, "extra-label"]}, "labels"),
        ({"assignees": [{"username": "someone"}]}, "assignee_count"),
        ({"confidential": True}, "confidential"),
        ({"references": {"full": "other/project#57"}}, "project_path"),
        ({"title": "A completely different title"}, "title"),
        ({"author": {"username": "not-the-bot"}}, "author_username"),
        ({"state": "closed"}, "state"),
    ],
)
def test_post_creation_verification_failure_marks_suspect_and_aborts(
    tmp_path, capsys, monkeypatch, overrides, expected_substr
):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(**overrides), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, _out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 2
    assert expected_substr in err

    ledger = requirement_issues.read_ledger(tmp_path, "t1")
    assert ledger["entries"]["REQ-001"]["status"] == "suspect"


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------


def test_missing_allow_classification_refused(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
        ],
        capsys,
    )
    assert code == 1
    assert "allow-classification" in err


def test_wrong_allow_classification_refused(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "restricted",
        ],
        capsys,
    )
    assert code == 1
    assert "allow-classification" in err


def test_as_bot_identity_mismatch_refused(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", "wrong-bot",
            "--allow-classification", "internal", "--apply", "--plan-digest", digest,
            "--i-know-this-is-mocked",
        ],
        capsys,
    )
    assert code == 1
    assert "does not match required bot identity" in err


def test_mock_guard_requires_i_know_this_is_mocked(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal", "--apply", "--plan-digest", digest,
        ],
        capsys,
    )
    assert code == 1
    assert "i-know-this-is-mocked" in err


def test_over_max_items_refuses_not_truncates(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    many_items = {
        "schema_version": 1, "gate_id": "G2",
        "items": [{"key": f"REQ-{i:03}", "title": "T", "description": "D"} for i in range(5)],
    }
    items_path = _write_items(tmp_path, many_items)
    _write_mock(tmp_path, {"identity": {"username": BOT}, "search": {}, "create": {}, "verify": {}}, monkeypatch)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal", "--max-items", "3",
        ],
        capsys,
    )
    assert code == 1
    assert "max-items" in err


def test_nonexistent_items_file_aborts_cleanly(tmp_path, capsys):
    _plan(tmp_path, "t1", capsys)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(tmp_path / "does-not-exist.json"),
            "--as-bot", BOT, "--allow-classification", "internal",
        ],
        capsys,
    )
    assert code == 1
    assert "unable to read --items" in err


def test_non_json_items_file_aborts_cleanly(tmp_path, capsys):
    _plan(tmp_path, "t1", capsys)
    bad_path = tmp_path / "not-json.txt"
    bad_path.write_text("this is not json {{{", encoding="utf-8")
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(bad_path),
            "--as-bot", BOT, "--allow-classification", "internal",
        ],
        capsys,
    )
    assert code == 1
    assert "not valid JSON" in err


def test_bad_title_aborts_full_cli_path_with_zero_gitlab_calls(tmp_path, capsys, monkeypatch):
    """End-to-end (not just the isolated `sanitize_items` unit test):
    drives the real `create-requirement-issues` CLI command with a
    rejected title, and proves via a monkeypatched `subprocess.run` that
    the abort happens before any GitLab call is even attempted -- no
    `_sanitized_artifact_field`-style substitute-and-continue behavior."""
    _plan(tmp_path, "t1", capsys)
    bad_items = {
        "schema_version": 1, "gate_id": "G2",
        "items": [{"key": "REQ-001", "title": "-bad title", "description": "ok"}],
    }
    items_path = _write_items(tmp_path, bad_items)

    def _boom(*args, **kwargs):
        raise AssertionError("no subprocess call should ever be attempted for a rejected item")

    monkeypatch.setattr(subprocess, "run", _boom)

    # --dry-run (default): must abort before printing any digest.
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal",
        ],
        capsys,
    )
    assert code == 1
    assert "must not start with" in err

    # --apply: sanitization runs before plan-digest comparison and before
    # any GitLab call, so this must abort identically, even with an
    # otherwise well-formed (but necessarily wrong, since no digest was
    # ever produced) --plan-digest.
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal", "--apply", "--plan-digest", "sha256:" + "0" * 64,
        ],
        capsys,
    )
    assert code == 1
    assert "must not start with" in err


def _force_gate(root: Path, task_id: str, *, status=None, required_reentry_gate=None, run_halted=None):
    graph, config, _metadata = runtime.build_graph_for_task(root, task_id)
    snapshot = graph.get_state(config)
    values = snapshot.values or {}
    gate = dict(values.get("lifecycle_gates", {}).get("G2") or {})
    if not gate:
        from agentic_sdlc_langgraph.export import _base_placeholder_gate

        gate = _base_placeholder_gate("G2")
    if status is not None:
        gate["status"] = status
    if required_reentry_gate is not None:
        gate["required_reentry_gate"] = required_reentry_gate
    patch: dict = {"lifecycle_gates": {"G2": gate}}
    if run_halted is not None:
        patch["run_halted"] = run_halted
    graph.update_state(config, patch)


def test_blocked_gate_status_refuses(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    _force_gate(tmp_path, "t1", status="blocked")
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal",
        ],
        capsys,
    )
    assert code == 2
    assert "not publish-eligible" in err


def test_invalidated_gate_status_refuses(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    _force_gate(tmp_path, "t1", status="invalidated")
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal",
        ],
        capsys,
    )
    assert code == 2
    assert "not publish-eligible" in err


def test_required_reentry_gate_refuses(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    _force_gate(tmp_path, "t1", required_reentry_gate="G1")
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal",
        ],
        capsys,
    )
    assert code == 2
    assert "required_reentry_gate" in err


def test_run_halted_refuses(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    _force_gate(tmp_path, "t1", run_halted=True)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal",
        ],
        capsys,
    )
    assert code == 2
    assert "halted" in err


def test_gate_not_in_derived_sequence_refuses(tmp_path, capsys, monkeypatch):
    """A task whose derived gate sequence never included G2 at all (here,
    forced via `--ignored-gates G2`) must be refused outright, not fall
    through to the same `gate_status: "pending"` default used for
    "in-sequence but not yet reached"."""
    code, _out, err = _run(
        ["plan", "--root", str(tmp_path), "--task-id", "t1", "--task", TASK_TEXT, "--ignored-gates", "G2"],
        capsys,
    )
    assert code == 0, err
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal",
        ],
        capsys,
    )
    assert code == 1
    assert "not part of task" in err


# --------------------------------------------------------------------------
# Concurrency / durability
# --------------------------------------------------------------------------


def test_second_apply_while_lock_held_aborts_with_holder_details(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)

    lock_path = requirement_issues.acquire_lock(tmp_path, "t1", break_lock=False)
    holder = json.loads(lock_path.read_text(encoding="utf-8"))
    try:
        code, _out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
        assert code == 2
        assert "already held" in err
        # The actual recorded holder pid/started_at, not just the bare
        # JSON key names, must appear in the error text.
        assert str(holder["pid"]) in err
        assert holder["started_at"] in err
    finally:
        requirement_issues.release_lock(lock_path)


def test_break_lock_overrides_held_lock(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)

    requirement_issues.acquire_lock(tmp_path, "t1", break_lock=False)
    code, out, err = _apply(tmp_path, "t1", items_path, digest, capsys, extra=["--break-lock"])
    assert code == 0, err
    assert json.loads(out)["results"][0]["status"] == "created"


def test_issue_created_but_ledger_write_skipped_next_run_finds_via_search(tmp_path, capsys, monkeypatch):
    """Simulates a crash between the real GitLab create and the ledger
    write completing: the next run's label search still finds the issue
    (forge-authoritative) and does not duplicate it."""
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)

    # No ledger entry was ever written for this item, but the forge
    # already has the issue (as if create succeeded before a crash).
    _write_mock(tmp_path, _reused_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 0, err
    assert json.loads(out)["results"][0]["status"] == "reused"


# --------------------------------------------------------------------------
# Plan digest
# --------------------------------------------------------------------------


def test_apply_without_plan_digest_refused(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    code, _out, err = _run(
        [
            "create-requirement-issues", "--root", str(tmp_path), "--task-id", "t1",
            "--project", "group/project", "--items", str(items_path), "--as-bot", BOT,
            "--allow-classification", "internal", "--apply", "--i-know-this-is-mocked",
        ],
        capsys,
    )
    assert code == 1
    assert "plan-digest" in err


def test_stale_wrong_digest_refused(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    code, _out, err = _apply(tmp_path, "t1", items_path, "sha256:" + "0" * 64, capsys)
    assert code == 2
    assert "mismatch" in err


def test_reenter_between_dry_run_and_apply_invalidates_digest(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)

    graph, config, metadata = runtime.build_graph_for_task(tmp_path, "t1")
    invalidate_gates(graph, config, "G2", "test", "tester", metadata.gate_sequence_ids)

    code, _out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 2
    # Eligibility fails first with a more specific message (the gate now
    # genuinely requires reentry) -- still refused, exit code 2 either way.
    assert "required_reentry_gate" in err


def test_reenter_mid_loop_aborts_at_next_item_boundary(tmp_path, monkeypatch):
    """Exercises `requirement_issues.run` directly (not through the CLI)
    with a `get_eligibility` stub that reports clean state for the
    preflight check and the first item, then a concurrent-reentry state
    from the second item onward -- proving the digest is genuinely
    re-checked at every item boundary, not just once up front."""
    two_items = {
        "schema_version": 1, "gate_id": "G2",
        "items": [
            {"key": "REQ-001", "title": "Support SSO login", "description": "As a user I want SSO login."},
            {"key": "REQ-002", "title": "Support MFA", "description": "As a user I want MFA."},
        ],
    }
    items_path = tmp_path / "items.json"
    items_path.write_text(json.dumps(two_items), encoding="utf-8")

    marker2 = requirement_issues.compute_marker("t1", "G2", "REQ-002")
    label2 = requirement_issues.item_label(marker2)
    mock = {
        "identity": {"username": BOT},
        "search": {_LABEL_KEY: [], f"agentic-sdlc,{label2}": []},
        "create": {_LABEL_KEY: {"iid": 57}, f"agentic-sdlc,{label2}": {"iid": 58}},
        "verify": {"57": _verify_payload(), "58": _verify_payload(labels=["agentic-sdlc", label2])},
    }
    _write_mock(tmp_path, mock, monkeypatch)

    clean = requirement_issues.Eligibility(
        run_halted=False, required_reentry_gate=None, gate_status="ready",
        re_entry_count=0, classification="internal",
    )
    dirty = requirement_issues.Eligibility(
        run_halted=False, required_reentry_gate=None, gate_status="ready",
        re_entry_count=1, classification="internal",  # a reenter happened -> re_entry_count changed
    )
    calls = {"n": 0}

    def get_eligibility():
        calls["n"] += 1
        return clean if calls["n"] <= 2 else dirty  # preflight + item 1 clean, item 2 dirty

    digest = requirement_issues.run(
        root=tmp_path, task_id="t1", project="group/project", items_source=str(items_path),
        as_bot=BOT, apply=False, plan_digest=None, allow_classification="internal",
        max_items=50, break_lock=False, i_know_this_is_mocked=False, get_eligibility=get_eligibility,
    )["plan_digest"]
    calls["n"] = 0

    with pytest.raises(requirement_issues.RequirementIssuesBlocked, match="REQ-002"):
        requirement_issues.run(
            root=tmp_path, task_id="t1", project="group/project", items_source=str(items_path),
            as_bot=BOT, apply=True, plan_digest=digest, allow_classification="internal",
            max_items=50, break_lock=False, i_know_this_is_mocked=True, get_eligibility=get_eligibility,
        )

    ledger = requirement_issues.read_ledger(tmp_path, "t1")
    assert ledger["entries"]["REQ-001"]["status"] == "created"
    assert "REQ-002" not in ledger["entries"]


def test_benign_gate_status_transition_alone_does_not_trip_digest(tmp_path, capsys, monkeypatch):
    """ready -> approved with no reenter/invalidate must not change the
    digest between a --dry-run and its matching --apply."""
    _plan(tmp_path, "t1", capsys)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(APPROVAL), encoding="utf-8")
    code, _out, err = _run(
        ["resume", "--root", str(tmp_path), "--task-id", "t1", "--decision", str(decision_path)], capsys
    )
    assert code == 0, err  # now suspended at G2, with G2 gate_decision already "ready"

    items_path = _write_items(tmp_path)
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)

    # Approve G2 -- a benign ready -> approved transition, no reenter.
    code, _out, err = _run(
        ["resume", "--root", str(tmp_path), "--task-id", "t1", "--decision", str(decision_path)], capsys
    )
    assert code == 0, err

    code, out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 0, err
    assert json.loads(out)["results"][0]["status"] == "created"


# --------------------------------------------------------------------------
# list-requirement-issues does not rebuild the graph
# --------------------------------------------------------------------------


def test_list_requirement_issues_reads_ledger_without_graph_config(tmp_path, capsys):
    """No graph-config.json exists for this task_id at all -- if
    `list-requirement-issues` tried to rebuild the graph it would raise
    `GraphConfigError`; it must not."""
    code, out, err = _run(["list-requirement-issues", "--root", str(tmp_path), "--task-id", "never-planned"], capsys)
    assert code == 0, err
    ledger = json.loads(out)
    assert ledger["entries"] == {}


# --------------------------------------------------------------------------
# Repo-health: never wired into graph dispatch
# --------------------------------------------------------------------------


def test_graph_module_never_references_requirement_issues():
    import agentic_sdlc_langgraph.graph as graph_module

    source = Path(graph_module.__file__).read_text(encoding="utf-8")
    assert "requirement_issues" not in source
    assert "requirement_ledger" not in source


# --------------------------------------------------------------------------
# Non-interference invariant
# --------------------------------------------------------------------------


def test_non_interference_with_lifecycle_gates_and_export(tmp_path, capsys, monkeypatch):
    _plan(tmp_path, "t1", capsys)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(APPROVAL), encoding="utf-8")
    _run(["resume", "--root", str(tmp_path), "--task-id", "t1", "--decision", str(decision_path)], capsys)
    # Now suspended at G2's human_approval interrupt.

    def _snapshot_gate():
        graph, config, _metadata = runtime.build_graph_for_task(tmp_path, "t1")
        return copy.deepcopy(graph.get_state(config).values.get("lifecycle_gates", {}).get("G2"))

    def _snapshot_export():
        graph, config, metadata = runtime.build_graph_for_task(tmp_path, "t1")
        record = export_run_record(
            graph.get_state(config).values,
            sequence_gate_ids=metadata.gate_sequence_ids,
            ignored_gate_ids=metadata.ignored_gate_ids,
        )
        record.pop("recorded_at")
        return record

    before_gate = _snapshot_gate()
    before_export = _snapshot_export()

    items_path = _write_items(tmp_path)

    # 1. dry-run
    _dry_run_digest(tmp_path, "t1", items_path, capsys)
    assert _snapshot_gate() == before_gate
    assert _snapshot_export() == before_export

    # 2. successful apply
    _write_mock(tmp_path, _create_mock(), monkeypatch)
    digest = _dry_run_digest(tmp_path, "t1", items_path, capsys)
    code, _out, err = _apply(tmp_path, "t1", items_path, digest, capsys)
    assert code == 0, err
    assert _snapshot_gate() == before_gate
    assert _snapshot_export() == before_export

    # 3. failed/aborted apply (stale digest)
    code, _out, err = _apply(tmp_path, "t1", items_path, "sha256:" + "1" * 64, capsys)
    assert code == 2
    assert _snapshot_gate() == before_gate
    assert _snapshot_export() == before_export

    # requirements_baseline_id is never written by this feature.
    graph, config, _metadata = runtime.build_graph_for_task(tmp_path, "t1")
    assert graph.get_state(config).values.get("requirements_baseline_id") is None
