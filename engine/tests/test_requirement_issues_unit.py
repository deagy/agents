"""Unit tests for `requirement_issues.py`'s backend-neutral policy logic:
marker/label helpers, item loading/validation, both sanitizers, plan
digest, ledger durability, and lock acquire/release. GitLab-call-level
behavior (existence check / create+verify / drift) is covered by
`test_requirement_issues_cli.py`, which exercises the full orchestration
through the CLI with mocked `gitlab_issue` calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from agentic_sdlc_langgraph import requirement_issues as ri


# --------------------------------------------------------------------------
# Marker / label
# --------------------------------------------------------------------------


def test_marker_is_hashed_not_raw_task_id():
    marker = ri.compute_marker("very-secret-task-id", "G2", "REQ-001")
    assert len(marker) == 16
    assert "very-secret-task-id" not in marker
    assert marker == ri.compute_marker("very-secret-task-id", "G2", "REQ-001")


def test_item_label_charset():
    marker = ri.compute_marker("t1", "G2", "REQ-001")
    label = ri.item_label(marker)
    assert label.startswith("agentic-sdlc-item-")
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in label)


# --------------------------------------------------------------------------
# Items file loading/validation
# --------------------------------------------------------------------------


def _items_bytes(items: list[dict], gate_id: str = "G2", schema_version: int = 1) -> bytes:
    return json.dumps({"schema_version": schema_version, "gate_id": gate_id, "items": items}).encode()


def test_parse_items_file_happy_path():
    raw = _items_bytes([{"key": "REQ-001", "title": "T", "description": "D"}])
    parsed = ri.parse_items_file(raw, max_items=50)
    assert parsed.gate_id == "G2"
    assert len(parsed.items) == 1
    assert parsed.items[0].content_hash.startswith("sha256:")


def test_parse_items_file_rejects_wrong_gate_id():
    raw = _items_bytes([{"key": "REQ-001", "title": "T", "description": "D"}], gate_id="G3")
    with pytest.raises(ri.RequirementIssuesError, match="gate_id must be 'G2'"):
        ri.parse_items_file(raw, max_items=50)


def test_parse_items_file_rejects_wrong_schema_version():
    raw = _items_bytes([{"key": "REQ-001", "title": "T", "description": "D"}], schema_version=2)
    with pytest.raises(ri.RequirementIssuesError, match="schema_version must be 1"):
        ri.parse_items_file(raw, max_items=50)


def test_parse_items_file_rejects_duplicate_keys():
    raw = _items_bytes(
        [{"key": "REQ-001", "title": "T", "description": "D"}, {"key": "REQ-001", "title": "T2", "description": "D2"}]
    )
    with pytest.raises(ri.RequirementIssuesError, match="duplicate item key"):
        ri.parse_items_file(raw, max_items=50)


def test_parse_items_file_rejects_bad_key_pattern():
    raw = _items_bytes([{"key": "bad key!", "title": "T", "description": "D"}])
    with pytest.raises(ri.RequirementIssuesError, match="does not match the required pattern"):
        ri.parse_items_file(raw, max_items=50)


def test_parse_items_file_refuses_over_max_items_never_truncates():
    raw = _items_bytes([{"key": f"REQ-{i:03}", "title": "T", "description": "D"} for i in range(5)])
    with pytest.raises(ri.RequirementIssuesError, match="exceeding --max-items"):
        ri.parse_items_file(raw, max_items=3)


def test_parse_items_file_rejects_empty_items():
    raw = _items_bytes([])
    with pytest.raises(ri.RequirementIssuesError, match="non-empty"):
        ri.parse_items_file(raw, max_items=50)


# --------------------------------------------------------------------------
# Title sanitization
# --------------------------------------------------------------------------


def test_sanitize_title_happy_path():
    assert ri.sanitize_title("  Support SSO login  ", "REQ-001") == "Support SSO login"


def test_sanitize_title_rejects_non_ascii_homoglyph():
    with pytest.raises(ri.RequirementIssuesError, match="non-printable-ASCII"):
        ri.sanitize_title("Suppоrt SSO login", "REQ-001")  # Cyrillic 'о'


def test_sanitize_title_rejects_leading_dash():
    with pytest.raises(ri.RequirementIssuesError, match="must not start with"):
        ri.sanitize_title("-rm -rf", "REQ-001")


def test_sanitize_title_rejects_leading_slash():
    with pytest.raises(ri.RequirementIssuesError, match="must not start with"):
        ri.sanitize_title("/assign @lead", "REQ-001")


def test_sanitize_title_rejects_empty_after_strip():
    with pytest.raises(ri.RequirementIssuesError, match="empty after"):
        ri.sanitize_title("   ", "REQ-001")


def test_sanitize_title_rejects_over_length():
    with pytest.raises(ri.RequirementIssuesError, match="exceeds 200"):
        ri.sanitize_title("x" * 201, "REQ-001")


# --------------------------------------------------------------------------
# Description sanitization -- bypass corpus
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sep", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_sanitize_description_rejects_forbidden_separator_before_quick_action(sep):
    description = f"hello{sep}/assign @lead"
    with pytest.raises(ri.RequirementIssuesError):
        ri.sanitize_description(description, "REQ-001")


def test_sanitize_description_rejects_lone_surrogate():
    with pytest.raises(ri.RequirementIssuesError, match="lone Unicode surrogate"):
        ri.sanitize_description("hello \ud800 world", "REQ-001")


def test_sanitize_description_rejects_quick_action_line():
    with pytest.raises(ri.RequirementIssuesError, match="quick-action"):
        ri.sanitize_description("intro\n/assign @lead\nmore", "REQ-001")


def test_sanitize_description_rejects_indented_quick_action_line():
    with pytest.raises(ri.RequirementIssuesError, match="quick-action"):
        ri.sanitize_description("intro\n   /confidential\nmore", "REQ-001")


def test_sanitize_description_rejects_reserved_ref_line():
    with pytest.raises(ri.RequirementIssuesError, match="reserved provenance"):
        ri.sanitize_description("intro\n> ref abc/G2/def\nmore", "REQ-001")


def test_sanitize_description_rejects_reserved_banner():
    with pytest.raises(ri.RequirementIssuesError, match="reserved provenance"):
        ri.sanitize_description(ri._PROVENANCE_BANNER, "REQ-001")


def test_sanitize_description_neutralizes_mentions_and_crossrefs():
    result = ri.sanitize_description("cc @lead see owner/repo#42 and #7", "REQ-001")
    assert "@lead" not in result
    assert "@​lead" in result
    assert "owner/repo#​42" in result
    assert "#​7" in result


def test_sanitize_description_rejects_over_length():
    with pytest.raises(ri.RequirementIssuesError, match="exceeds 8000"):
        ri.sanitize_description("x" * 8001, "REQ-001")


def test_sanitize_description_length_cap_enforced_after_neutralization():
    """The 8000-char cap must be checked *after* mention/cross-ref
    neutralization (step 5, which runs after step 4's neutralization,
    per `sanitize_description`'s docstring) -- neutralization can only
    grow the string (zero-width-space insertion), never shrink it, so a
    description just under the raw cap but pushed over it by
    neutralization must still be rejected."""
    mentions = " @a" * 5  # each neutralized occurrence grows by 1 char (zwsp insertion)
    filler = "x" * (7999 - len(mentions))
    description = filler + mentions
    assert len(description) == 7999  # under the cap *before* neutralization
    assert len(ri._neutralize_references(description)) == 8004  # over the cap *after*
    with pytest.raises(ri.RequirementIssuesError, match="exceeds 8000"):
        ri.sanitize_description(description, "REQ-001")


def test_sanitize_description_fences_backtick_runs_with_longer_fence():
    description = "here is a run of backticks: ```` inline"
    fence_len = ri._fence_length(description)
    assert fence_len == 5  # longest run (4) + 1
    body = ri.render_body("t1", "G2", "abc123", description)
    assert "`" * fence_len in body
    assert "`" * (fence_len + 1) not in body


def test_sanitize_description_minimum_fence_is_three_backticks():
    assert ri._fence_length("no backticks here") == 3


# --------------------------------------------------------------------------
# Rejected title/description never produces GitLab side effects (proves no
# `_sanitized_artifact_field`-style substitute-and-continue behavior).
# --------------------------------------------------------------------------


def test_sanitize_items_aborts_before_any_gitlab_call(monkeypatch: pytest.MonkeyPatch):
    from agentic_sdlc_langgraph import gitlab_issue

    def _boom(*args, **kwargs):
        raise AssertionError("no GitLab call should ever be attempted for a rejected item")

    monkeypatch.setattr(gitlab_issue, "search_gitlab_issues_by_labels", _boom)
    monkeypatch.setattr(gitlab_issue, "create_gitlab_issue", _boom)

    items = [ri.Item(key="REQ-001", title="-bad title", description="ok", content_hash="sha256:x")]
    with pytest.raises(ri.RequirementIssuesError, match="must not start with"):
        ri.sanitize_items("t1", "G2", items)


# --------------------------------------------------------------------------
# Plan digest
# --------------------------------------------------------------------------


def _digest_kwargs(**overrides):
    base = dict(
        task_id="t1", gate_id="G2", project="group/project", items_raw=b'{"a": 1}',
        item_keys=["REQ-001"], item_hashes={"REQ-001": "sha256:x"},
        run_halted=False, required_reentry_gate=None, gate_status="pending", re_entry_count=0,
    )
    base.update(overrides)
    return base


def test_plan_digest_stable_for_identical_inputs():
    d1 = ri.compute_plan_digest(**_digest_kwargs())
    d2 = ri.compute_plan_digest(**_digest_kwargs())
    assert d1 == d2


def test_plan_digest_excludes_raw_gate_status_benign_transition():
    """A benign ready->approved transition alone must not change the
    digest -- only whether status is in {blocked, invalidated} matters."""
    d_ready = ri.compute_plan_digest(**_digest_kwargs(gate_status="ready"))
    d_approved = ri.compute_plan_digest(**_digest_kwargs(gate_status="approved"))
    assert d_ready == d_approved


def test_plan_digest_changes_when_becoming_blocked():
    d_ready = ri.compute_plan_digest(**_digest_kwargs(gate_status="ready"))
    d_blocked = ri.compute_plan_digest(**_digest_kwargs(gate_status="blocked"))
    assert d_ready != d_blocked


def test_plan_digest_changes_on_reentry_count():
    d1 = ri.compute_plan_digest(**_digest_kwargs(re_entry_count=0))
    d2 = ri.compute_plan_digest(**_digest_kwargs(re_entry_count=1))
    assert d1 != d2


def test_check_publish_eligibility_blocks_on_run_halted():
    with pytest.raises(ri.RequirementIssuesBlocked, match="halted"):
        ri.check_publish_eligibility(run_halted=True, required_reentry_gate=None, gate_status="pending")


def test_check_publish_eligibility_blocks_on_required_reentry_gate():
    with pytest.raises(ri.RequirementIssuesBlocked, match="required_reentry_gate"):
        ri.check_publish_eligibility(run_halted=False, required_reentry_gate="G1", gate_status="pending")


@pytest.mark.parametrize("status", ["blocked", "invalidated"])
def test_check_publish_eligibility_blocks_on_status(status):
    with pytest.raises(ri.RequirementIssuesBlocked, match="not publish-eligible"):
        ri.check_publish_eligibility(run_halted=False, required_reentry_gate=None, gate_status=status)


def test_check_publish_eligibility_allows_pending_or_ready():
    ri.check_publish_eligibility(run_halted=False, required_reentry_gate=None, gate_status="pending")
    ri.check_publish_eligibility(run_halted=False, required_reentry_gate=None, gate_status="ready")


# --------------------------------------------------------------------------
# Ledger durability
# --------------------------------------------------------------------------


def test_ledger_round_trip(tmp_path: Path):
    ledger = ri.read_ledger(tmp_path, "t1")
    assert ledger["entries"] == {}
    ledger["entries"]["REQ-001"] = {"item_key": "REQ-001", "status": "created"}
    ri.write_ledger(tmp_path, "t1", ledger)

    path = tmp_path / ".agentic-sdlc" / "runs" / "t1" / "requirement-issues.json"
    assert path.is_file()
    assert oct(path.stat().st_mode)[-3:] == "600"

    reloaded = ri.read_ledger(tmp_path, "t1")
    assert reloaded["entries"]["REQ-001"]["status"] == "created"


def test_ledger_write_uses_same_directory_temp_file(tmp_path: Path):
    ledger = ri.read_ledger(tmp_path, "t1")
    path = tmp_path / ".agentic-sdlc" / "runs" / "t1" / "requirement-issues.json"
    path.parent.mkdir(parents=True)

    seen_dirs = []
    real_mkstemp = __import__("tempfile").mkstemp

    def _spy_mkstemp(*args, **kwargs):
        seen_dirs.append(kwargs.get("dir"))
        return real_mkstemp(*args, **kwargs)

    with mock.patch("tempfile.mkstemp", side_effect=_spy_mkstemp):
        ri.write_ledger(tmp_path, "t1", ledger)

    assert seen_dirs == [path.parent]


def test_ledger_write_fsyncs_the_directory(tmp_path: Path):
    ledger = ri.read_ledger(tmp_path, "t1")
    real_fsync = os.fsync
    fsync_calls = []

    def _spy_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    with mock.patch("os.fsync", side_effect=_spy_fsync):
        ri.write_ledger(tmp_path, "t1", ledger)

    # Called at least twice: once for the data file, once for the directory.
    assert len(fsync_calls) >= 2


# --------------------------------------------------------------------------
# Lock
# --------------------------------------------------------------------------


def test_acquire_lock_then_second_acquire_is_blocked(tmp_path: Path):
    lock_path = ri.acquire_lock(tmp_path, "t1", break_lock=False)
    assert lock_path.is_file()
    with pytest.raises(ri.RequirementIssuesBlocked, match="already held"):
        ri.acquire_lock(tmp_path, "t1", break_lock=False)


def test_break_lock_overrides_a_held_lock(tmp_path: Path):
    ri.acquire_lock(tmp_path, "t1", break_lock=False)
    # Without --break-lock this would raise; with it, it succeeds.
    lock_path = ri.acquire_lock(tmp_path, "t1", break_lock=True)
    assert lock_path.is_file()


def test_release_lock_allows_reacquire(tmp_path: Path):
    lock_path = ri.acquire_lock(tmp_path, "t1", break_lock=False)
    ri.release_lock(lock_path)
    lock_path2 = ri.acquire_lock(tmp_path, "t1", break_lock=False)
    assert lock_path2.is_file()


def test_lock_records_holder_details(tmp_path: Path):
    lock_path = ri.acquire_lock(tmp_path, "t1", break_lock=False)
    holder = json.loads(lock_path.read_text(encoding="utf-8"))
    assert isinstance(holder["pid"], int)
    assert isinstance(holder["started_at"], str) and holder["started_at"]

    try:
        ri.acquire_lock(tmp_path, "t1", break_lock=False)
    except ri.RequirementIssuesBlocked as exc:
        message = str(exc)
        # The *actual* recorded pid/started_at values must appear, not
        # just the literal JSON key names -- a generic message containing
        # the bare words "pid"/"started_at" (with no real holder data)
        # must not pass this test.
        assert str(holder["pid"]) in message
        assert holder["started_at"] in message
    else:
        pytest.fail("expected RequirementIssuesBlocked")
