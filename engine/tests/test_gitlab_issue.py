"""Tests for `agentic_sdlc_langgraph.gitlab_issue`.

Covers:

- `parse_gitlab_issue_uri`'s shape parsing/rejection, porting the kernel
  test `test_parse_gitlab_issue_uri`
  (plugins/agentic-sdlc/test/test_agentic_sdlc.py) onto this port.
- `fetch_gitlab_issue` reading from `AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE`
  when set (never shelling out to `glab`), and rejecting a response
  missing a title/state.
- `gitlab_issue_uri`'s build-and-validate round trip.
- `resolve_issue_reference`'s `<project-path>#<iid>` parsing, including
  its malformed-reference and `None`-passthrough cases -- the function
  `cli.py`'s `plan` and `service.py`'s `create_task` both call.
"""

from __future__ import annotations

import json

import pytest

from agentic_sdlc_langgraph.gitlab_issue import (
    fetch_gitlab_issue,
    gitlab_issue_uri,
    parse_gitlab_issue_uri,
    resolve_issue_reference,
)


def test_parse_gitlab_issue_uri():
    parsed = parse_gitlab_issue_uri("gitlab-issue:group/project:issues/42")
    assert parsed == {"project_path": "group/project", "iid": "42"}
    assert parse_gitlab_issue_uri("gitlab-issue:missing-fields") is None
    assert parse_gitlab_issue_uri("gitlab-mr:group/project:merge_requests/42:approval/1:approver/alice") is None


def test_fetch_gitlab_issue_reads_mock_file(tmp_path, monkeypatch):
    mock_issue = {
        "iid": 42,
        "title": "Support SSO login for enterprise customers",
        "state": "opened",
        "web_url": "https://gitlab.example.com/group/project/-/issues/42",
        "updated_at": "2030-01-01T00:00:00Z",
    }
    mock_file = tmp_path / "issue.json"
    mock_file.write_text(json.dumps(mock_issue), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE", str(mock_file))

    result = fetch_gitlab_issue("group/project", 42)
    assert result == mock_issue
    # monkeypatch restores the environment automatically after the test.


def test_fetch_gitlab_issue_rejects_missing_title(tmp_path, monkeypatch):
    mock_file = tmp_path / "bad_issue.json"
    mock_file.write_text(json.dumps({"iid": 99, "state": "opened"}), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE", str(mock_file))

    with pytest.raises(ValueError, match="missing a title"):
        fetch_gitlab_issue("group/project", 99)


def test_fetch_gitlab_issue_rejects_unrecognized_state(tmp_path, monkeypatch):
    mock_file = tmp_path / "bad_state.json"
    mock_file.write_text(json.dumps({"iid": 99, "title": "x", "state": "merged"}), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE", str(mock_file))

    with pytest.raises(ValueError, match="unrecognized state"):
        fetch_gitlab_issue("group/project", 99)


def test_gitlab_issue_uri_builds_and_validates():
    assert gitlab_issue_uri("group/project", 42) == "gitlab-issue:group/project:issues/42"


def test_resolve_issue_reference_returns_none_for_none():
    assert resolve_issue_reference(None) is None


def test_resolve_issue_reference_rejects_malformed_value():
    with pytest.raises(ValueError, match="project-path.*iid"):
        resolve_issue_reference("not-a-valid-reference")


def test_resolve_issue_reference_fetches_and_builds_uri(tmp_path, monkeypatch):
    mock_issue = {
        "iid": 42,
        "title": "Support SSO login for enterprise customers",
        "state": "opened",
        "web_url": None,
        "updated_at": None,
    }
    mock_file = tmp_path / "issue.json"
    mock_file.write_text(json.dumps(mock_issue), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE", str(mock_file))

    assert resolve_issue_reference("group/project#42") == "gitlab-issue:group/project:issues/42"
