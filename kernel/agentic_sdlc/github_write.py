"""GitHub read-only helpers for `request-gate-reviewers`
(`agentic_sdlc/gate_reviewers.py`).

**Read-only in this version.** Every function here issues `gh api ... GET`
calls only. There is no POST/DELETE review-request capability anywhere in
this module (or anywhere else in the kernel) -- requesting PR reviewers
requires a GitHub token with `Pull requests: write` scope, which has no
narrower equivalent and also permits editing/closing PRs and changing
labels. Introducing that write capability is a real permission-escalation
decision that needs explicit human sign-off before it is built; this module
deliberately does not stub it out either. See `gate_reviewers.py`'s module
docstring for the full reasoning.

Mirrors `gitlab_write.py`'s conventions (a single mock-file environment
variable multiplexing every canned response, `_run_<tool>`/`_parse_<tool>_json`
subprocess helpers, per-function mock-shape docstrings) but for `gh api`
instead of `glab api`. This is a *new*, forge-distinct module, not an
extension of `gitlab_write.py` -- the two forges are never mixed in one
mock file or one set of functions.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

# Distinct from gitlab_write.ISSUE_CREATE_MOCK_ENV_VAR -- this module has no
# issue-create (or any write) concept at all, so a separate name avoids
# implying a write capability that does not exist here.
GITHUB_READ_MOCK_ENV_VAR = "AGENTIC_SDLC_TEST_GITHUB_READ_FILE"

_GH_TIMEOUT_SECONDS = 30


class PRNotFound(ValueError):
    """Raised by `fetch_github_pr` on a 404. Kept as a distinct exception
    (rather than requiring callers to string-match a generic ValueError) so
    `gate_reviewers.run()` can attach precise, structural error context."""


def _load_mock() -> dict[str, Any] | None:
    mock_path = os.environ.get(GITHUB_READ_MOCK_ENV_VAR)
    if not mock_path:
        return None
    payload = json.loads(Path(mock_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{GITHUB_READ_MOCK_ENV_VAR} must contain a JSON object")
    return payload


def _run_gh(argv: list[str]) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-gh-") as cwd:
        try:
            return subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                timeout=_GH_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise _gh_launch_error(argv, "timed out", exc) from exc
        except OSError as exc:
            raise _gh_launch_error(argv, "failed to start", exc) from exc


def _gh_launch_error(argv: list[str], verb: str, exc: BaseException) -> ValueError:
    command = " ".join(argv[:2]) if len(argv) >= 2 else (argv[0] if argv else "gh")
    return ValueError(f"`{command}` {verb}: {exc.__class__.__name__} -- is gh installed and reachable?")


def _parse_gh_json(raw_stdout: bytes, context: str):
    try:
        return json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context}: gh exited 0 but stdout was not valid JSON ({exc})") from exc


def _is_not_found_error(stderr_text: str) -> bool:
    """`gh api` surfaces GitHub's HTTP status as plain text within its error
    output rather than a structured field (same limitation documented on
    gitlab_write._is_link_unavailable_error), so detecting a 404 means
    looking for it in `stderr`."""
    return "404" in stderr_text or "Not Found" in stderr_text


def verify_github_identity(expected_login: str) -> str:
    """Calls `gh api user`, asserts the authenticated `login` matches
    `expected_login` case-insensitively, and returns the verified login.
    Mock convention: `mock["identity"]` is the raw `gh api user` response
    object."""
    mock = _load_mock()
    if mock is not None:
        raw = mock.get("identity")
        if not isinstance(raw, dict):
            raise ValueError(f"mocked {GITHUB_READ_MOCK_ENV_VAR} response has no 'identity' object")
    else:
        result = _run_gh(["gh", "api", "user"])
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
            raise ValueError(f"unable to verify GitHub identity: {detail}")
        raw = _parse_gh_json(result.stdout, "verify_github_identity")
        if not isinstance(raw, dict):
            raise ValueError("GitHub user API response must be a JSON object")

    login = raw.get("login")
    if not isinstance(login, str) or not login:
        raise ValueError("GitHub user API response is missing a login")
    if login.lower() != expected_login.lower():
        raise ValueError(
            f"authenticated GitHub identity {login!r} does not match required bot identity "
            f"{expected_login!r} -- point your gh credential config at the bot's credentials"
        )
    return login


def fetch_github_pr(repo: str, pr: int) -> dict[str, Any]:
    """`GET /repos/{repo}/pulls/{pr}`. Raises `PRNotFound` on a 404. Mock
    convention: `mock["pr"]` is the raw PR response object, or absent/None
    to simulate a 404."""
    mock = _load_mock()
    if mock is not None:
        raw = mock.get("pr")
        if raw is None:
            raise PRNotFound(f"mocked PR lookup for {repo}#{pr} is missing (simulated 404)")
        if not isinstance(raw, dict):
            raise ValueError("mocked pr response must be a JSON object")
        return raw

    encoded_repo_parts = "/".join(quote(part, safe="") for part in repo.split("/", 1))
    result = _run_gh(["gh", "api", f"repos/{encoded_repo_parts}/pulls/{pr}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        if _is_not_found_error(detail):
            raise PRNotFound(f"GitHub PR {repo}#{pr} not found: {detail}")
        raise ValueError(f"unable to fetch GitHub PR {repo}#{pr}: {detail}")
    raw = _parse_gh_json(result.stdout, "fetch_github_pr")
    if not isinstance(raw, dict):
        raise ValueError("GitHub PR response must be a JSON object")
    return raw


def fetch_requested_reviewers(repo: str, pr: int) -> list[str]:
    """`GET /repos/{repo}/pulls/{pr}/requested_reviewers`. Returns just the
    user-login list -- team review requests are out of scope for a
    per-login report (see `gate_reviewers.py`). Mock convention:
    `mock["requested_reviewers"]` is the raw API response object
    (`{"users": [...], "teams": [...]}`); absent defaults to no requests."""
    mock = _load_mock()
    if mock is not None:
        raw = mock.get("requested_reviewers", {"users": [], "teams": []})
    else:
        encoded_repo_parts = "/".join(quote(part, safe="") for part in repo.split("/", 1))
        result = _run_gh(["gh", "api", f"repos/{encoded_repo_parts}/pulls/{pr}/requested_reviewers"])
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
            raise ValueError(f"unable to fetch requested reviewers for {repo}#{pr}: {detail}")
        raw = _parse_gh_json(result.stdout, "fetch_requested_reviewers")
    if not isinstance(raw, dict):
        raise ValueError("GitHub requested_reviewers response must be a JSON object")
    users = raw.get("users", [])
    if not isinstance(users, list):
        raise ValueError("GitHub requested_reviewers 'users' field must be a JSON array")
    logins: list[str] = []
    for entry in users:
        login = entry.get("login") if isinstance(entry, dict) else None
        if isinstance(login, str) and login:
            logins.append(login)
    return logins


def check_github_user_exists(login: str) -> bool:
    """`GET /users/{login}`. An exact lookup (404, or exactly one match) --
    unlike GitLab's search-based `GET /users?username=`, there is no
    ambiguous multi-match case here, so no `github-user-ambiguous` reason
    code exists anywhere in `gate_reviewers.py`. Mock convention:
    `mock["users"][login]` is a bool."""
    mock = _load_mock()
    if mock is not None:
        users = mock.get("users", {})
        if login not in users:
            raise ValueError(f"mocked users response is missing an entry for login {login!r}")
        return bool(users[login])

    encoded_login = quote(login, safe="")
    result = _run_gh(["gh", "api", f"users/{encoded_login}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        if _is_not_found_error(detail):
            return False
        raise ValueError(f"unable to check GitHub user {login!r}: {detail}")
    return True


def check_github_collaborator(repo: str, login: str) -> bool:
    """`GET /repos/{repo}/collaborators/{login}`. Returns `True` on a 204
    (login is a collaborator), `False` on a 404 (not a collaborator). Mock
    convention: `mock["collaborators"]["{repo}:{login}"]` is a bool."""
    mock = _load_mock()
    if mock is not None:
        collaborators = mock.get("collaborators", {})
        key = f"{repo}:{login}"
        if key not in collaborators:
            raise ValueError(f"mocked collaborators response is missing an entry for {key!r}")
        return bool(collaborators[key])

    encoded_repo_parts = "/".join(quote(part, safe="") for part in repo.split("/", 1))
    encoded_login = quote(login, safe="")
    result = _run_gh(["gh", "api", f"repos/{encoded_repo_parts}/collaborators/{encoded_login}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        if _is_not_found_error(detail):
            return False
        raise ValueError(f"unable to check GitHub collaborator {login!r} on {repo}: {detail}")
    return True
