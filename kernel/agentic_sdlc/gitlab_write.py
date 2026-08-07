"""GitLab *write* helpers for `create-gate-issues` / `list-gate-issues`
(`agentic_sdlc/gate_issues.py`).

Ported near-verbatim from `agentic_sdlc_langgraph/agentic_sdlc_langgraph/
gitlab_issue.py`'s bottom section (`verify_gitlab_identity`,
`search_gitlab_issues_by_labels`, `create_gitlab_issue`,
`fetch_gitlab_issue_verification`, and the `ISSUE_CREATE_MOCK_ENV_VAR`
multiplexed mock-file convention, lines ~50-73 and ~219-412 of that file).
The kernel had no GitLab *write* surface before this module -- only the
read-only `fetch_gitlab_issue` (`agentic_sdlc/__init__.py:520-554`, mirrored
by the engine's own `fetch_gitlab_issue` at `gitlab_issue.py:139-179`) and
the MR-approval-state reader (`fetch_gitlab_mr_approvals`,
`agentic_sdlc/__init__.py:458-483`).

This is a *forward* port (engine -> kernel), the opposite direction of most
of this repository's engine/kernel relationship (the engine usually ports
*from* the kernel -- see `agentic_sdlc_langgraph`'s module docstrings). That
is deliberate here: `create-gate-issues` needs `authority_gitlab_username()`
/ `authorities.json`, which is an overlay concept that only exists in the
kernel (see `gate_issues.py`'s module docstring for the full reasoning).
`test_gate_issues.py`'s `PortIntegrityTests` class asserts `FIXED_LABEL`
and the mock env-var name stay identical between both copies so the two
do not silently drift apart.

New functions not present in the engine's `gitlab_issue.py` at all
(`resolve_gitlab_user_id`, `update_gitlab_issue_assignee`,
`create_gitlab_issue_link`, `fetch_gitlab_issue_assignment_verification`)
extend the *same* mock-file convention with additional top-level keys
(`"users"`, `"assignee_update"`, `"link"`) documented on each function --
this repository's own extension of that convention, not a divergence from
the ported functions above them.

`list_mr_notes`/`create_mr_note`/`update_mr_note`/`fetch_mr_note` are a
further extension for `publish-gate-status` / `list-gate-status`
(`agentic_sdlc/gate_status.py`), reusing the same `ISSUE_CREATE_MOCK_ENV_VAR`
mock file with new top-level keys (`"notes_list"`, `"notes_create"`,
`"notes_update"`, `"notes_fetch"`) rather than a distinct env var, since
they mirror the issue-comment functions' shape. They operate on GitLab's MR
"notes" endpoint, not the issue "comments"/"discussions" endpoints used
above -- a merge request's notes are a materially different resource from a
GitLab issue's, even though both are called "notes" in GitLab's own API
terminology.

`fetch_gitlab_mr` is a further, read-only-only extension for
`request-gate-reviewers-gitlab` (`agentic_sdlc/gate_reviewers_gitlab.py`),
reusing the same mock file with a new top-level `"mr"` key. It is the
GitLab counterpart of `github_write.fetch_github_pr` -- a single
`GET .../merge_requests/:iid` call, never a write -- and raises `MRNotFound`
on a 404, mirroring `github_write.PRNotFound`.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

FIXED_LABEL = "agentic-sdlc"

# Identical name/convention to the engine's gitlab_issue.py -- see module
# docstring and test_gate_issues.py's PortIntegrityTests class.
ISSUE_CREATE_MOCK_ENV_VAR = "AGENTIC_SDLC_TEST_ISSUE_CREATE_FILE"

_GLAB_TIMEOUT_SECONDS = 30


def _load_issue_create_mock() -> dict[str, Any] | None:
    mock_path = os.environ.get(ISSUE_CREATE_MOCK_ENV_VAR)
    if not mock_path:
        return None
    payload = json.loads(Path(mock_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{ISSUE_CREATE_MOCK_ENV_VAR} must contain a JSON object")
    return payload


def _run_glab(argv: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-glab-") as cwd:
        try:
            return subprocess.run(
                argv,
                cwd=cwd,
                input=input_bytes,
                capture_output=True,
                timeout=_GLAB_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise _glab_launch_error(argv, "timed out", exc) from exc
        except OSError as exc:
            raise _glab_launch_error(argv, "failed to start", exc) from exc


def _glab_launch_error(argv: list[str], verb: str, exc: BaseException) -> ValueError:
    command = " ".join(argv[:2]) if len(argv) >= 2 else (argv[0] if argv else "glab")
    return ValueError(f"`{command}` {verb}: {exc.__class__.__name__} -- is glab installed and reachable?")


def _parse_glab_json(raw_stdout: bytes, context: str):
    try:
        return json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context}: glab exited 0 but stdout was not valid JSON ({exc})") from exc


def verify_gitlab_identity(expected_username: str) -> str:
    """Port of the engine's `verify_gitlab_identity`. Calls `glab api user`,
    asserts the authenticated `username` matches `expected_username`
    case-insensitively, and returns the verified username."""
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("identity")
        if not isinstance(raw, dict):
            raise ValueError(f"mocked {ISSUE_CREATE_MOCK_ENV_VAR} response has no 'identity' object")
    else:
        result = _run_glab(["glab", "api", "user"])
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
            raise ValueError(f"unable to verify GitLab identity: {detail}")
        raw = _parse_glab_json(result.stdout, "verify_gitlab_identity")
        if not isinstance(raw, dict):
            raise ValueError("GitLab user API response must be a JSON object")

    username = raw.get("username")
    if not isinstance(username, str) or not username:
        raise ValueError("GitLab user API response is missing a username")
    if username.lower() != expected_username.lower():
        raise ValueError(
            f"authenticated GitLab identity {username!r} does not match required bot identity "
            f"{expected_username!r} -- point your glab credential config at the bot's credentials"
        )
    return username


def search_gitlab_issues_by_labels(project_path: str, labels: list[str]) -> list[dict[str, Any]]:
    """Port of the engine's `search_gitlab_issues_by_labels`."""
    key = ",".join(labels)
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("search", {}).get(key, [])
        if not isinstance(raw, list):
            raise ValueError(f"mocked search response for labels {key!r} must be a JSON array")
        return raw

    encoded_project = quote(project_path, safe="")
    label_param = quote(key, safe="")
    result = _run_glab(
        ["glab", "api", f"projects/{encoded_project}/issues?labels={label_param}&state=all&per_page=20"]
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        raise ValueError(f"unable to search GitLab issues in {project_path} for labels {labels}: {detail}")
    raw = _parse_glab_json(result.stdout, "search_gitlab_issues_by_labels")
    if not isinstance(raw, list):
        raise ValueError("GitLab issue search response must be a JSON array")
    return raw


def create_gitlab_issue(
    project_path: str, title: str, description: str, labels: list[str], assignee_ids: list[int] | None = None
) -> int:
    """Port of the engine's `create_gitlab_issue`, extended with an optional
    `assignee_ids` field on the request body -- needed for approval issues
    (`gate_issues.py` §5.4), unused (omitted from the body entirely, not
    sent as an empty list) for gate issues, which must never carry an
    assignee (§5.3)."""
    key = ",".join(labels)
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("create", {}).get(key)
        if not isinstance(raw, dict):
            raise ValueError(f"mocked create response for labels {key!r} must be a JSON object")
    else:
        encoded_project = quote(project_path, safe="")
        body_payload: dict[str, Any] = {"title": title, "description": description, "labels": labels}
        if assignee_ids:
            body_payload["assignee_ids"] = list(assignee_ids)
        body = json.dumps(body_payload).encode("utf-8")
        tmp_dir = tempfile.mkdtemp(prefix="agentic-sdlc-glab-create-")
        try:
            fd, body_path = tempfile.mkstemp(dir=tmp_dir, prefix="issue-body-", suffix=".json")
            try:
                os.write(fd, body)
            finally:
                os.close(fd)
            os.chmod(body_path, 0o600)
            argv = [
                "glab", "api", f"projects/{encoded_project}/issues",
                "--method", "POST", "--input", body_path,
            ]
            try:
                result = subprocess.run(
                    argv,
                    cwd=tmp_dir,
                    capture_output=True,
                    timeout=_GLAB_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise _glab_launch_error(["glab", "api"], "timed out", exc) from exc
            except OSError as exc:
                raise _glab_launch_error(["glab", "api"], "failed to start", exc) from exc
        finally:
            for entry in Path(tmp_dir).glob("issue-body-*"):
                entry.unlink(missing_ok=True)
            Path(tmp_dir).rmdir()
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
            raise ValueError(f"unable to create GitLab issue in {project_path}: {detail}")
        raw = _parse_glab_json(result.stdout, "create_gitlab_issue")
        if not isinstance(raw, dict):
            raise ValueError("GitLab issue create response must be a JSON object")

    iid = raw.get("iid")
    if not isinstance(iid, int):
        raise ValueError("GitLab issue create response is missing an integer 'iid'")
    return iid


def _extract_verification(raw: dict[str, Any], iid: int) -> dict[str, Any]:
    labels = raw.get("labels")
    labels = list(labels) if isinstance(labels, list) else []
    assignees = raw.get("assignees")
    assignee_count = len(assignees) if isinstance(assignees, list) else 0
    assignee_usernames = sorted(
        {
            entry.get("username")
            for entry in (assignees if isinstance(assignees, list) else [])
            if isinstance(entry, dict) and isinstance(entry.get("username"), str)
        }
    )
    author = raw.get("author")
    author_username = author.get("username") if isinstance(author, dict) else None

    project_path_field = raw.get("project_path")
    if project_path_field is None:
        references = raw.get("references")
        if isinstance(references, dict):
            full_ref = references.get("full")
            if isinstance(full_ref, str) and "#" in full_ref:
                project_path_field = full_ref.rsplit("#", 1)[0]

    return {
        "iid": iid,
        "title": raw.get("title"),
        "state": raw.get("state"),
        "labels": labels,
        "assignee_count": assignee_count,
        "assignee_usernames": assignee_usernames,
        "confidential": bool(raw.get("confidential", False)),
        "project_path": project_path_field,
        "author_username": author_username,
        "web_url": raw.get("web_url"),
    }


def _fetch_raw_issue(project_path: str, iid: int, *, context: str) -> dict[str, Any]:
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("verify", {}).get(str(iid))
        if not isinstance(raw, dict):
            raise ValueError(f"mocked verification response for iid {iid} must be a JSON object")
        return raw
    encoded_project = quote(project_path, safe="")
    result = _run_glab(["glab", "api", f"projects/{encoded_project}/issues/{iid}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        raise ValueError(f"unable to fetch {context} for {project_path} issue {iid}: {detail}")
    raw = _parse_glab_json(result.stdout, context)
    if not isinstance(raw, dict):
        raise ValueError(f"{context} response must be a JSON object")
    return raw


def fetch_gitlab_issue_verification(project_path: str, iid: int) -> dict[str, Any]:
    """Port of the engine's `fetch_gitlab_issue_verification`. Deliberately
    a SEPARATE function from any read-only `fetch_gitlab_issue` -- see that
    function's own docstring (`agentic_sdlc/__init__.py:520-554`) for why
    this must not be a widening of it. Returns
    `{iid, title, state, labels, assignee_count, assignee_usernames,
    confidential, project_path, author_username, web_url}`.
    `assignee_usernames` is included here (unlike the engine's copy) purely
    as a superset field -- callers that must not depend on assignee
    identity (gate issues) simply never read it; see
    `fetch_gitlab_issue_assignment_verification` below for the function
    whose entire *purpose* is reading it, per the human's explicit,
    narrowly-scoped reversal for approval subtasks only."""
    raw = _fetch_raw_issue(project_path, iid, context="fetch_gitlab_issue_verification")
    return _extract_verification(raw, iid)


def fetch_gitlab_issue_assignment_verification(project_path: str, iid: int) -> dict[str, Any]:
    """Sibling of `fetch_gitlab_issue_verification`, not a widening of it
    (see that function's docstring, and `gate_issues.py` §5.4). Reading
    assignee identity here is the human's explicit, narrowly-scoped
    reversal of the kernel's usual data-minimization posture, and it is
    scoped to approval subtasks only -- gate issues must keep using
    `fetch_gitlab_issue_verification` and must never branch on
    `assignee_usernames`. Returns the same shape as
    `fetch_gitlab_issue_verification` (which already includes
    `assignee_usernames`); this function exists so call sites are explicit
    about *why* they are allowed to read it."""
    raw = _fetch_raw_issue(project_path, iid, context="fetch_gitlab_issue_assignment_verification")
    return _extract_verification(raw, iid)


def resolve_gitlab_user_id(username: str) -> list[dict[str, Any]]:
    """`GET /users?username=<u>`. Returns the raw list of matching user
    objects (each with at least `id`, `username`, `state`) -- callers
    decide what "exactly one active match" means (`gate_issues.py` §5.4
    step 3). Mock convention: `mock["users"][username]` is that same raw
    list."""
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("users", {}).get(username, [])
        if not isinstance(raw, list):
            raise ValueError(f"mocked users response for username {username!r} must be a JSON array")
        return raw
    username_param = quote(username, safe="")
    result = _run_glab(["glab", "api", f"users?username={username_param}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        raise ValueError(f"unable to resolve GitLab username {username!r}: {detail}")
    raw = _parse_glab_json(result.stdout, "resolve_gitlab_user_id")
    if not isinstance(raw, list):
        raise ValueError("GitLab users response must be a JSON array")
    return raw


def update_gitlab_issue_assignee(project_path: str, iid: int, assignee_ids: list[int]) -> None:
    """`PUT projects/:id/issues/:iid` with `assignee_ids`. Only ever called
    behind `--reconcile-assignees` (`gate_issues.py` §3.3) -- an explicit
    operator opt-in to overwrite GitLab's assignee state. Mock convention:
    `mock["assignee_update"][str(iid)]` is either any JSON object (treated
    as success) or `{"error": "<message>"}` (raises with that message)."""
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("assignee_update", {}).get(str(iid), {})
        if isinstance(raw, dict) and "error" in raw:
            raise ValueError(f"unable to update assignee for issue {iid}: {raw['error']}")
        return
    encoded_project = quote(project_path, safe="")
    body = json.dumps({"assignee_ids": list(assignee_ids)}).encode("utf-8")
    tmp_dir = tempfile.mkdtemp(prefix="agentic-sdlc-glab-assignee-")
    try:
        fd, body_path = tempfile.mkstemp(dir=tmp_dir, prefix="assignee-", suffix=".json")
        try:
            os.write(fd, body)
        finally:
            os.close(fd)
        os.chmod(body_path, 0o600)
        argv = [
            "glab", "api", f"projects/{encoded_project}/issues/{iid}",
            "--method", "PUT", "--input", body_path,
        ]
        result = subprocess.run(argv, cwd=tmp_dir, capture_output=True, timeout=_GLAB_TIMEOUT_SECONDS, check=False)
    finally:
        for entry in Path(tmp_dir).glob("assignee-*"):
            entry.unlink(missing_ok=True)
        Path(tmp_dir).rmdir()
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        raise ValueError(f"unable to update assignee for issue {project_path}#{iid}: {detail}")


def _is_link_unavailable_error(stderr_text: str) -> bool:
    """Pure substring check factored out of `create_gitlab_issue_link` so
    it can be unit tested directly without a live `glab` binary: `glab`
    surfaces GitLab's HTTP status as plain text within its error output
    rather than a structured field, so detecting "Issue Links API is
    unavailable on this instance" (403/404) means looking for those codes
    in `stderr`."""
    return "403" in stderr_text or "404" in stderr_text


class IssueLinksUnavailable(ValueError):
    """Raised by `create_gitlab_issue_link` when the Issue Links API is not
    available on the target instance (403/404) -- callers must fail closed
    (`gate_issues.py` §4.2), never silently downgrade to skipping the
    link."""


def list_mr_notes(project_path: str, mr_iid: int, *, page: int, per_page: int = 100) -> list[dict[str, Any]]:
    """`GET projects/:id/merge_requests/:iid/notes?per_page=<n>&page=<p>` --
    one page of an MR's notes (GitLab's term for both regular comments and
    system-generated activity notes). Used by `gate_status.py`'s
    `GitlabForgeAdapter`, which owns pagination and the `MAX_COMMENT_PAGES`
    cap; this function fetches exactly one page. Mirrors the issue-comment
    functions above rather than a widening of them -- MRs use GitLab's
    "notes" endpoint, not "comments" (that terminology is GitLab-issue-only).
    Mock convention: `mock["notes_list"][f"{project_path}:{mr_iid}"][str(page)]`
    is that page's raw note array (missing key == empty page)."""
    mock = _load_issue_create_mock()
    key = f"{project_path}:{mr_iid}"
    if mock is not None:
        raw = mock.get("notes_list", {}).get(key, {}).get(str(page), [])
        if not isinstance(raw, list):
            raise ValueError(f"mocked notes_list response for {key!r} page {page} must be a JSON array")
        return raw

    encoded_project = quote(project_path, safe="")
    result = _run_glab(
        ["glab", "api", f"projects/{encoded_project}/merge_requests/{mr_iid}/notes?per_page={per_page}&page={page}"]
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        raise ValueError(f"unable to list MR notes for {project_path} MR {mr_iid} page {page}: {detail}")
    raw = _parse_glab_json(result.stdout, "list_mr_notes")
    if not isinstance(raw, list):
        raise ValueError("GitLab MR notes response must be a JSON array")
    return raw


def create_mr_note(project_path: str, mr_iid: int, body: str) -> int:
    """`POST projects/:id/merge_requests/:iid/notes`. Mock convention:
    `mock["notes_create"][f"{project_path}:{mr_iid}"]` is `{"id": <int>}`."""
    key = f"{project_path}:{mr_iid}"
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("notes_create", {}).get(key)
        if not isinstance(raw, dict):
            raise ValueError(f"mocked notes_create response for {key!r} must be a JSON object")
    else:
        encoded_project = quote(project_path, safe="")
        body_payload = {"body": body}
        tmp_dir = tempfile.mkdtemp(prefix="agentic-sdlc-glab-note-")
        try:
            fd, body_path = tempfile.mkstemp(dir=tmp_dir, prefix="note-", suffix=".json")
            try:
                os.write(fd, json.dumps(body_payload).encode("utf-8"))
            finally:
                os.close(fd)
            os.chmod(body_path, 0o600)
            argv = [
                "glab", "api", f"projects/{encoded_project}/merge_requests/{mr_iid}/notes",
                "--method", "POST", "--input", body_path,
            ]
            result = subprocess.run(argv, cwd=tmp_dir, capture_output=True, timeout=_GLAB_TIMEOUT_SECONDS, check=False)
        finally:
            for entry in Path(tmp_dir).glob("note-*"):
                entry.unlink(missing_ok=True)
            Path(tmp_dir).rmdir()
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
            raise ValueError(f"unable to create MR note on {project_path} MR {mr_iid}: {detail}")
        raw = _parse_glab_json(result.stdout, "create_mr_note")
        if not isinstance(raw, dict):
            raise ValueError("GitLab MR note create response must be a JSON object")

    note_id = raw.get("id")
    if not isinstance(note_id, int):
        raise ValueError("GitLab MR note create response is missing an integer 'id'")
    return note_id


def update_mr_note(project_path: str, mr_iid: int, note_id: int, body: str) -> None:
    """`PUT projects/:id/merge_requests/:iid/notes/:note_id`. Mock
    convention: `mock["notes_update"][str(note_id)]` is either any JSON
    object (success) or `{"error": "<message>"}` (raises with that
    message)."""
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("notes_update", {}).get(str(note_id), {})
        if isinstance(raw, dict) and "error" in raw:
            raise ValueError(f"unable to update MR note {note_id}: {raw['error']}")
        return
    encoded_project = quote(project_path, safe="")
    body_payload = {"body": body}
    tmp_dir = tempfile.mkdtemp(prefix="agentic-sdlc-glab-note-update-")
    try:
        fd, body_path = tempfile.mkstemp(dir=tmp_dir, prefix="note-", suffix=".json")
        try:
            os.write(fd, json.dumps(body_payload).encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(body_path, 0o600)
        argv = [
            "glab", "api", f"projects/{encoded_project}/merge_requests/{mr_iid}/notes/{note_id}",
            "--method", "PUT", "--input", body_path,
        ]
        result = subprocess.run(argv, cwd=tmp_dir, capture_output=True, timeout=_GLAB_TIMEOUT_SECONDS, check=False)
    finally:
        for entry in Path(tmp_dir).glob("note-*"):
            entry.unlink(missing_ok=True)
        Path(tmp_dir).rmdir()
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        raise ValueError(f"unable to update MR note {note_id} for {project_path} MR {mr_iid}: {detail}")


def fetch_mr_note(project_path: str, mr_iid: int, note_id: int) -> dict[str, Any]:
    """`GET projects/:id/merge_requests/:iid/notes/:note_id` -- used only
    for the post-create/post-update re-fetch-and-verify step
    (`gate_status.py` section 3). Mock convention:
    `mock["notes_fetch"][str(note_id)]` is the raw note object."""
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("notes_fetch", {}).get(str(note_id))
        if not isinstance(raw, dict):
            raise ValueError(f"mocked notes_fetch response for note {note_id} must be a JSON object")
        return raw
    encoded_project = quote(project_path, safe="")
    result = _run_glab(["glab", "api", f"projects/{encoded_project}/merge_requests/{mr_iid}/notes/{note_id}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        raise ValueError(f"unable to fetch MR note {note_id} for {project_path} MR {mr_iid}: {detail}")
    raw = _parse_glab_json(result.stdout, "fetch_mr_note")
    if not isinstance(raw, dict):
        raise ValueError("GitLab MR note fetch response must be a JSON object")
    return raw


def create_gitlab_issue_link(
    project_path: str, source_iid: int, target_project_path: str, target_iid: int, link_type: str = "relates_to"
) -> dict[str, Any]:
    """`POST projects/:id/issues/:iid/links`. Only called when the operator
    passes `--link-type relates_to` (`gate_issues.py` §4.2) -- the
    always-on floor is the markdown `> parent <project>#<iid>` description
    line, not this API call. Mock convention:
    `mock["link"][str(source_iid)]` is either any JSON object (success) or
    `{"error_status": 403 | 404, "error": "<message>"}` (raises
    `IssueLinksUnavailable`)."""
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("link", {}).get(str(source_iid))
        if not isinstance(raw, dict):
            raise ValueError(f"mocked link response for iid {source_iid} must be a JSON object")
        if "error_status" in raw:
            raise IssueLinksUnavailable(
                f"GitLab Issue Links API unavailable for {project_path}#{source_iid} "
                f"(HTTP {raw['error_status']}): {raw.get('error', 'no detail')}"
            )
        return raw
    encoded_project = quote(project_path, safe="")
    encoded_target_project = quote(target_project_path, safe="")
    body = json.dumps(
        {"target_project_id": encoded_target_project, "target_issue_iid": target_iid, "link_type": link_type}
    ).encode("utf-8")
    tmp_dir = tempfile.mkdtemp(prefix="agentic-sdlc-glab-link-")
    try:
        fd, body_path = tempfile.mkstemp(dir=tmp_dir, prefix="link-", suffix=".json")
        try:
            os.write(fd, body)
        finally:
            os.close(fd)
        os.chmod(body_path, 0o600)
        argv = [
            "glab", "api", f"projects/{encoded_project}/issues/{source_iid}/links",
            "--method", "POST", "--input", body_path,
        ]
        result = subprocess.run(argv, cwd=tmp_dir, capture_output=True, timeout=_GLAB_TIMEOUT_SECONDS, check=False)
    finally:
        for entry in Path(tmp_dir).glob("link-*"):
            entry.unlink(missing_ok=True)
        Path(tmp_dir).rmdir()
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        if _is_link_unavailable_error(detail):
            raise IssueLinksUnavailable(
                f"GitLab Issue Links API unavailable for {project_path}#{source_iid}: {detail}"
            )
        raise ValueError(f"unable to create issue link for {project_path}#{source_iid}: {detail}")
    return _parse_glab_json(result.stdout, "create_gitlab_issue_link")


class MRNotFound(ValueError):
    """Raised by `fetch_gitlab_mr` on a 404. Mirrors `github_write.PRNotFound`
    -- a distinct exception so `gate_reviewers_gitlab.run()` can attach
    precise, structural error context rather than string-matching a generic
    `ValueError`."""


def _is_not_found_error(stderr_text: str) -> bool:
    """`glab api` surfaces GitLab's HTTP status as plain text within its
    error output rather than a structured field (same limitation documented
    on `_is_link_unavailable_error` above), so detecting a 404 means looking
    for it in `stderr`."""
    return "404" in stderr_text or "Not Found" in stderr_text


def fetch_gitlab_mr(project_path: str, mr_iid: int) -> dict[str, Any]:
    """`GET projects/:id/merge_requests/:iid`. Raises `MRNotFound` on a 404.
    Read-only counterpart of `github_write.fetch_github_pr`. Mock
    convention: `mock["mr"]` is the raw MR response object, or absent/None
    to simulate a 404."""
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("mr")
        if raw is None:
            raise MRNotFound(f"mocked MR lookup for {project_path}!{mr_iid} is missing (simulated 404)")
        if not isinstance(raw, dict):
            raise ValueError("mocked mr response must be a JSON object")
        return raw

    encoded_project = quote(project_path, safe="")
    result = _run_glab(["glab", "api", f"projects/{encoded_project}/merge_requests/{mr_iid}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
        if _is_not_found_error(detail):
            raise MRNotFound(f"GitLab MR {project_path}!{mr_iid} not found: {detail}")
        raise ValueError(f"unable to fetch GitLab MR {project_path}!{mr_iid}: {detail}")
    raw = _parse_glab_json(result.stdout, "fetch_gitlab_mr")
    if not isinstance(raw, dict):
        raise ValueError("GitLab MR response must be a JSON object")
    return raw
