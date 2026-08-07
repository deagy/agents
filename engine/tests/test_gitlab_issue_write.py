"""Tests for `gitlab_issue.py`'s four `create-requirement-issues` GitLab
calls (`verify_gitlab_identity`, `search_gitlab_issues_by_labels`,
`create_gitlab_issue`, `fetch_gitlab_issue_verification`), all mocked via
`AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE` -- see that env var's docstring in
`gitlab_issue.py` for the shared mock-file shape.

Zero-network: every test here asserts `subprocess.run` is never invoked
when the mock file is set, by monkeypatching it to raise if called.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from agentic_sdlc_langgraph import gitlab_issue


def _never_call_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when the mock env var is set")

    monkeypatch.setattr(subprocess, "run", _boom)


def _write_mock(tmp_path, payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_file = tmp_path / "mock.json"
    mock_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv(gitlab_issue.ISSUE_CREATE_MOCK_ENV_VAR, str(mock_file))


def test_verify_gitlab_identity_zero_network(tmp_path, monkeypatch):
    _never_call_subprocess(monkeypatch)
    _write_mock(tmp_path, {"identity": {"username": "svc-agentic-sdlc"}}, monkeypatch)
    assert gitlab_issue.verify_gitlab_identity("svc-agentic-sdlc") == "svc-agentic-sdlc"
    assert gitlab_issue.verify_gitlab_identity("SVC-Agentic-SDLC") == "svc-agentic-sdlc"


def test_verify_gitlab_identity_mismatch_raises(tmp_path, monkeypatch):
    _never_call_subprocess(monkeypatch)
    _write_mock(tmp_path, {"identity": {"username": "someone-else"}}, monkeypatch)
    with pytest.raises(ValueError, match="does not match required bot identity"):
        gitlab_issue.verify_gitlab_identity("svc-agentic-sdlc")


def test_search_gitlab_issues_by_labels_zero_network(tmp_path, monkeypatch):
    _never_call_subprocess(monkeypatch)
    _write_mock(
        tmp_path,
        {"search": {"agentic-sdlc,agentic-sdlc-item-abc": [{"iid": 5, "state": "opened", "labels": ["agentic-sdlc"]}]}},
        monkeypatch,
    )
    result = gitlab_issue.search_gitlab_issues_by_labels("group/project", ["agentic-sdlc", "agentic-sdlc-item-abc"])
    assert result == [{"iid": 5, "state": "opened", "labels": ["agentic-sdlc"]}]


def test_search_gitlab_issues_by_labels_unknown_key_returns_empty(tmp_path, monkeypatch):
    _never_call_subprocess(monkeypatch)
    _write_mock(tmp_path, {"search": {}}, monkeypatch)
    assert gitlab_issue.search_gitlab_issues_by_labels("group/project", ["agentic-sdlc", "agentic-sdlc-item-x"]) == []


def test_create_gitlab_issue_zero_network(tmp_path, monkeypatch):
    _never_call_subprocess(monkeypatch)
    _write_mock(tmp_path, {"create": {"agentic-sdlc,agentic-sdlc-item-abc": {"iid": 57}}}, monkeypatch)
    iid = gitlab_issue.create_gitlab_issue(
        "group/project", "Title", "Body", ["agentic-sdlc", "agentic-sdlc-item-abc"]
    )
    assert iid == 57


def test_create_gitlab_issue_missing_iid_raises(tmp_path, monkeypatch):
    _never_call_subprocess(monkeypatch)
    _write_mock(tmp_path, {"create": {"agentic-sdlc,agentic-sdlc-item-abc": {}}}, monkeypatch)
    with pytest.raises(ValueError, match="missing an integer 'iid'"):
        gitlab_issue.create_gitlab_issue("group/project", "Title", "Body", ["agentic-sdlc", "agentic-sdlc-item-abc"])


def test_fetch_gitlab_issue_verification_zero_network_and_extraction(tmp_path, monkeypatch):
    _never_call_subprocess(monkeypatch)
    _write_mock(
        tmp_path,
        {
            "verify": {
                "57": {
                    "title": "Support SSO login",
                    "state": "opened",
                    "labels": ["agentic-sdlc", "agentic-sdlc-item-abc"],
                    "assignees": [{"username": "someone"}],
                    "confidential": False,
                    "references": {"full": "group/project#57"},
                    "author": {"username": "svc-agentic-sdlc"},
                    "web_url": "https://gitlab.example.com/group/project/-/issues/57",
                }
            }
        },
        monkeypatch,
    )
    result = gitlab_issue.fetch_gitlab_issue_verification("group/project", 57)
    assert result == {
        "iid": 57,
        "title": "Support SSO login",
        "state": "opened",
        "labels": ["agentic-sdlc", "agentic-sdlc-item-abc"],
        "assignee_count": 1,
        "confidential": False,
        "project_path": "group/project",
        "author_username": "svc-agentic-sdlc",
        "web_url": "https://gitlab.example.com/group/project/-/issues/57",
    }


# --------------------------------------------------------------------------
# Unhandled subprocess failure modes (timeout / missing `glab` binary) must
# produce a clean `ValueError` abort, not a raw traceback, and must not
# leak the private temp-directory path used for cwd/request bodies.
# --------------------------------------------------------------------------


def _assert_clean_and_no_path_leak(exc_info, tmp_dir_hint: str = "agentic-sdlc-glab-"):
    message = str(exc_info.value)
    assert tmp_dir_hint not in message
    assert "/tmp" not in message


def test_verify_gitlab_identity_timeout_is_clean_abort(monkeypatch):
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["glab", "api", "user"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(ValueError, match="timed out") as exc_info:
        gitlab_issue.verify_gitlab_identity("svc-agentic-sdlc")
    _assert_clean_and_no_path_leak(exc_info)


def test_verify_gitlab_identity_missing_binary_is_clean_abort(monkeypatch):
    def _missing(*args, **kwargs):
        raise FileNotFoundError("glab")

    monkeypatch.setattr(subprocess, "run", _missing)
    with pytest.raises(ValueError, match="failed to start") as exc_info:
        gitlab_issue.verify_gitlab_identity("svc-agentic-sdlc")
    _assert_clean_and_no_path_leak(exc_info)


def test_search_gitlab_issues_by_labels_timeout_is_clean_abort(monkeypatch):
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["glab", "api"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(ValueError, match="timed out") as exc_info:
        gitlab_issue.search_gitlab_issues_by_labels("group/project", ["agentic-sdlc"])
    _assert_clean_and_no_path_leak(exc_info)


def test_search_gitlab_issues_by_labels_missing_binary_is_clean_abort(monkeypatch):
    def _missing(*args, **kwargs):
        raise FileNotFoundError("glab")

    monkeypatch.setattr(subprocess, "run", _missing)
    with pytest.raises(ValueError, match="failed to start") as exc_info:
        gitlab_issue.search_gitlab_issues_by_labels("group/project", ["agentic-sdlc"])
    _assert_clean_and_no_path_leak(exc_info)


def test_create_gitlab_issue_timeout_is_clean_abort(monkeypatch):
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["glab", "api"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(ValueError, match="timed out") as exc_info:
        gitlab_issue.create_gitlab_issue("group/project", "Title", "Body", ["agentic-sdlc"])
    _assert_clean_and_no_path_leak(exc_info)


def test_create_gitlab_issue_missing_binary_is_clean_abort(monkeypatch):
    def _missing(*args, **kwargs):
        raise FileNotFoundError("glab")

    monkeypatch.setattr(subprocess, "run", _missing)
    with pytest.raises(ValueError, match="failed to start") as exc_info:
        gitlab_issue.create_gitlab_issue("group/project", "Title", "Body", ["agentic-sdlc"])
    _assert_clean_and_no_path_leak(exc_info)


def test_fetch_gitlab_issue_verification_timeout_is_clean_abort(monkeypatch):
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["glab", "api"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(ValueError, match="timed out") as exc_info:
        gitlab_issue.fetch_gitlab_issue_verification("group/project", 57)
    _assert_clean_and_no_path_leak(exc_info)


def test_fetch_gitlab_issue_verification_missing_binary_is_clean_abort(monkeypatch):
    def _missing(*args, **kwargs):
        raise FileNotFoundError("glab")

    monkeypatch.setattr(subprocess, "run", _missing)
    with pytest.raises(ValueError, match="failed to start") as exc_info:
        gitlab_issue.fetch_gitlab_issue_verification("group/project", 57)
    _assert_clean_and_no_path_leak(exc_info)


# --------------------------------------------------------------------------
# `glab` exiting 0 with malformed/non-JSON stdout must also abort cleanly,
# not raise an unhandled json.JSONDecodeError.
# --------------------------------------------------------------------------


def _fake_completed(stdout: bytes = b"not json {{{", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["glab"], returncode=returncode, stdout=stdout, stderr=b"")


def test_verify_gitlab_identity_malformed_json_is_clean_abort(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed())
    with pytest.raises(ValueError, match="not valid JSON") as exc_info:
        gitlab_issue.verify_gitlab_identity("svc-agentic-sdlc")
    _assert_clean_and_no_path_leak(exc_info)


def test_search_gitlab_issues_by_labels_malformed_json_is_clean_abort(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed())
    with pytest.raises(ValueError, match="not valid JSON") as exc_info:
        gitlab_issue.search_gitlab_issues_by_labels("group/project", ["agentic-sdlc"])
    _assert_clean_and_no_path_leak(exc_info)


def test_create_gitlab_issue_malformed_json_is_clean_abort(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed())
    with pytest.raises(ValueError, match="not valid JSON") as exc_info:
        gitlab_issue.create_gitlab_issue("group/project", "Title", "Body", ["agentic-sdlc"])
    _assert_clean_and_no_path_leak(exc_info)


def test_fetch_gitlab_issue_verification_malformed_json_is_clean_abort(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed())
    with pytest.raises(ValueError, match="not valid JSON") as exc_info:
        gitlab_issue.fetch_gitlab_issue_verification("group/project", 57)
    _assert_clean_and_no_path_leak(exc_info)


# --------------------------------------------------------------------------
# Real (non-mocked) `subprocess.run` success path -- distinct from the
# `AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE` mock bypass above. Captures the
# actual argv/kwargs passed to `subprocess.run` and asserts the documented
# invariants (argv list, explicit timeout, explicit cwd, private temp file
# for `create_gitlab_issue`'s body, 0600 mode, unlinked afterward, no
# secret/content on argv).
# --------------------------------------------------------------------------


def test_verify_gitlab_identity_real_subprocess_success_path(monkeypatch):
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _fake_completed(stdout=json.dumps({"username": "svc-agentic-sdlc"}).encode())

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert gitlab_issue.verify_gitlab_identity("svc-agentic-sdlc") == "svc-agentic-sdlc"

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ["glab", "api", "user"]
    assert isinstance(argv, list)
    assert kwargs["timeout"] == gitlab_issue._GLAB_TIMEOUT_SECONDS
    assert kwargs["cwd"] is not None


def test_search_gitlab_issues_by_labels_real_subprocess_success_path(monkeypatch):
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _fake_completed(stdout=b"[]")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = gitlab_issue.search_gitlab_issues_by_labels("group/project", ["agentic-sdlc", "agentic-sdlc-item-abc"])
    assert result == []

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[0] == "glab"
    assert argv[1] == "api"
    assert "state=all" in argv[2]
    assert "labels=agentic-sdlc%2Cagentic-sdlc-item-abc" in argv[2]
    assert kwargs["timeout"] == gitlab_issue._GLAB_TIMEOUT_SECONDS
    assert kwargs["cwd"] is not None


def test_fetch_gitlab_issue_verification_real_subprocess_success_path(monkeypatch):
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _fake_completed(
            stdout=json.dumps(
                {
                    "title": "x", "state": "opened", "labels": ["agentic-sdlc"], "assignees": [],
                    "confidential": False, "references": {"full": "group/project#57"},
                    "author": {"username": "svc-agentic-sdlc"}, "web_url": None,
                }
            ).encode()
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = gitlab_issue.fetch_gitlab_issue_verification("group/project", 57)
    assert result["author_username"] == "svc-agentic-sdlc"

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ["glab", "api", "projects/group%2Fproject/issues/57"]
    assert kwargs["timeout"] == gitlab_issue._GLAB_TIMEOUT_SECONDS
    assert kwargs["cwd"] is not None


def test_create_gitlab_issue_real_subprocess_success_path(monkeypatch, tmp_path):
    calls = []
    observed_body_path_during_call = {}

    def _fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        # The `--input <path>` argument must point at a real, currently
        # existing, 0600 file -- captured *during* the call, before this
        # module's own `finally` cleanup unlinks it.
        input_idx = argv.index("--input") + 1
        body_path = argv[input_idx]
        observed_body_path_during_call["path"] = body_path
        observed_body_path_during_call["existed_during_call"] = os.path.isfile(body_path)
        observed_body_path_during_call["mode_during_call"] = oct(os.stat(body_path).st_mode)[-3:]
        return _fake_completed(stdout=json.dumps({"iid": 57}).encode())

    monkeypatch.setattr(subprocess, "run", _fake_run)
    iid = gitlab_issue.create_gitlab_issue(
        "group/project", "a secret title", "a secret description", ["agentic-sdlc", "agentic-sdlc-item-abc"]
    )
    assert iid == 57

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[0] == "glab"
    assert argv[1] == "api"
    assert "projects/group%2Fproject/issues" in argv
    assert "--method" in argv and "POST" in argv
    assert "--input" in argv
    # Title/description must never appear as a literal argv element --
    # they travel only via the request-body file.
    assert "a secret title" not in argv
    assert "a secret description" not in argv
    assert kwargs["timeout"] == gitlab_issue._GLAB_TIMEOUT_SECONDS
    assert kwargs["cwd"] is not None

    assert observed_body_path_during_call["existed_during_call"] is True
    assert observed_body_path_during_call["mode_during_call"] == "600"
    # Unlinked (and its parent temp dir removed) after the call returns.
    assert not os.path.exists(observed_body_path_during_call["path"])


def test_fetch_gitlab_issue_verification_direct_project_path_field_wins(tmp_path, monkeypatch):
    _never_call_subprocess(monkeypatch)
    _write_mock(
        tmp_path,
        {
            "verify": {
                "9": {
                    "title": "x", "state": "opened", "labels": [], "assignees": [], "confidential": False,
                    "project_path": "explicit/path", "references": {"full": "other/path#9"},
                    "author": {"username": "bot"}, "web_url": None,
                }
            }
        },
        monkeypatch,
    )
    result = gitlab_issue.fetch_gitlab_issue_verification("group/project", 9)
    assert result["project_path"] == "explicit/path"
