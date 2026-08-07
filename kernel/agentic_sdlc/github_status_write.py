"""GitHub *write* helpers for `publish-gate-status` / `list-gate-status`
(`agentic_sdlc/gate_status.py`).

NAMING NOTE: this module would naturally have been named `github_write.py`
(the GitHub-forge counterpart to `gitlab_write.py`), but that name was
already occupied in this checkout by an unrelated, independently
in-progress, uncommitted module (`agentic_sdlc/github_write.py`, backing
`request-gate-reviewers` / `gate_reviewers.py`) discovered mid-task -- a
*read-only* module by its own docstring ("GitHub read-only helpers... There
is no POST/DELETE... capability anywhere in this module"), so there is no
functional overlap, but reusing its name would have silently mixed two
unrelated features' code and mock-file conventions into one file. This
module is named `github_status_write.py` instead to avoid that collision
without touching or depending on the other (unreviewed, not part of this
task) module. Flagged for a human to reconcile naming across both features
before either lands; see this task's completion report.

Otherwise follows `gitlab_write.py`'s exact conventions (see that module's
docstring): subprocess argv lists (never `shell=True`), JSON request bodies
written to a `0600` temp file and passed via `--input <path>` (never on the
argv, where they would be visible in `ps`/process listings), and a
multiplexed mock-file environment variable
(`AGENTIC_SDLC_TEST_GITHUB_WRITE_FILE`) for deterministic testing without a
real `gh` binary or network access.

Only the fields `gate_status.py` is allowed to read from a GitHub API
response are ever extracted here: a comment's `id`, `body`, author `login`,
and (always `False` for GitHub -- the issue-comments API has no "system
note" concept the way GitLab's notes API does) `is_system`. Reactions,
`award_emoji`, and any other field are never read, persisted, or requested
via a separate endpoint -- see `gate_status.py`'s own docstring for why.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

# Distinct from the unrelated github_write.py module's GITHUB_READ_MOCK_ENV_VAR
# (see module docstring) -- read and write mock fixtures for the two GitHub
# features are never accidentally cross-wired by sharing one variable.
GITHUB_WRITE_MOCK_ENV_VAR = "AGENTIC_SDLC_TEST_GITHUB_WRITE_FILE"

_GH_TIMEOUT_SECONDS = 30


def _load_github_write_mock() -> dict[str, Any] | None:
    mock_path = os.environ.get(GITHUB_WRITE_MOCK_ENV_VAR)
    if not mock_path:
        return None
    payload = json.loads(Path(mock_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{GITHUB_WRITE_MOCK_ENV_VAR} must contain a JSON object")
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


def _run_gh_write(argv: list[str], body_payload: dict[str, Any], *, tmp_prefix: str, verb: str) -> bytes:
    """Shared helper for POST/PATCH calls: writes `body_payload` to a `0600`
    same-filesystem temp file and passes it via `--input <path>`, mirroring
    `gitlab_write.create_gitlab_issue`'s convention exactly."""
    body = json.dumps(body_payload).encode("utf-8")
    tmp_dir = tempfile.mkdtemp(prefix=tmp_prefix)
    try:
        fd, body_path = tempfile.mkstemp(dir=tmp_dir, prefix="body-", suffix=".json")
        try:
            os.write(fd, body)
        finally:
            os.close(fd)
        os.chmod(body_path, 0o600)
        full_argv = argv + ["--input", body_path]
        try:
            result = subprocess.run(
                full_argv, cwd=tmp_dir, capture_output=True, timeout=_GH_TIMEOUT_SECONDS, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise _gh_launch_error(["gh", "api"], "timed out", exc) from exc
        except OSError as exc:
            raise _gh_launch_error(["gh", "api"], "failed to start", exc) from exc
    finally:
        for entry in Path(tmp_dir).glob("body-*"):
            entry.unlink(missing_ok=True)
        Path(tmp_dir).rmdir()
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        raise ValueError(f"unable to {verb}: {detail}")
    return result.stdout


def verify_github_identity(expected_username: str) -> str:
    """Calls `gh api user`, asserts the authenticated `login` matches
    `expected_username` case-insensitively, and returns the verified
    login. Mirrors `gitlab_write.verify_gitlab_identity`."""
    mock = _load_github_write_mock()
    if mock is not None:
        raw = mock.get("identity")
        if not isinstance(raw, dict):
            raise ValueError(f"mocked {GITHUB_WRITE_MOCK_ENV_VAR} response has no 'identity' object")
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
    if login.lower() != expected_username.lower():
        raise ValueError(
            f"authenticated GitHub identity {login!r} does not match required bot identity "
            f"{expected_username!r} -- point your gh credential config at the bot's credentials"
        )
    return login


def list_pr_comments(repo: str, pr: int, *, page: int, per_page: int = 100) -> list[dict[str, Any]]:
    """`GET repos/<repo>/issues/<pr>/comments?per_page=<n>&page=<p>` -- one
    page of a PR's issue-level comments. Callers (`gate_status.py`'s
    `GithubForgeAdapter`) own pagination and the `MAX_COMMENT_PAGES` cap;
    this function fetches exactly one page and never guesses about
    subsequent pages. Mock convention: `mock["list"][f"{repo}#{pr}"][str(page)]`
    is that page's raw comment array (missing key == empty page)."""
    mock = _load_github_write_mock()
    key = f"{repo}#{pr}"
    if mock is not None:
        raw = mock.get("list", {}).get(key, {}).get(str(page), [])
        if not isinstance(raw, list):
            raise ValueError(f"mocked list response for {key!r} page {page} must be a JSON array")
        return raw

    encoded_repo_parts = "/".join(quote(part, safe="") for part in repo.split("/", 1))
    result = _run_gh(["gh", "api", f"repos/{encoded_repo_parts}/issues/{pr}/comments?per_page={per_page}&page={page}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        raise ValueError(f"unable to list PR comments for {repo}#{pr} page {page}: {detail}")
    raw = _parse_gh_json(result.stdout, "list_pr_comments")
    if not isinstance(raw, list):
        raise ValueError("GitHub PR comments response must be a JSON array")
    return raw


def create_pr_comment(repo: str, pr: int, body: str) -> int:
    """`POST repos/<repo>/issues/<pr>/comments`. Mock convention:
    `mock["create"][f"{repo}#{pr}"]` is `{"id": <int>}`."""
    key = f"{repo}#{pr}"
    mock = _load_github_write_mock()
    if mock is not None:
        raw = mock.get("create", {}).get(key)
        if not isinstance(raw, dict):
            raise ValueError(f"mocked create response for {key!r} must be a JSON object")
    else:
        encoded_repo_parts = "/".join(quote(part, safe="") for part in repo.split("/", 1))
        argv = ["gh", "api", f"repos/{encoded_repo_parts}/issues/{pr}/comments", "--method", "POST"]
        stdout = _run_gh_write(
            argv, {"body": body}, tmp_prefix="agentic-sdlc-gh-comment-", verb=f"create PR comment on {repo}#{pr}"
        )
        raw = _parse_gh_json(stdout, "create_pr_comment")
        if not isinstance(raw, dict):
            raise ValueError("GitHub PR comment create response must be a JSON object")

    comment_id = raw.get("id")
    if not isinstance(comment_id, int):
        raise ValueError("GitHub PR comment create response is missing an integer 'id'")
    return comment_id


def update_pr_comment(repo: str, comment_id: int, body: str) -> None:
    """`PATCH repos/<repo>/issues/comments/<comment_id>`. Mock convention:
    `mock["update"][str(comment_id)]` is either any JSON object (success)
    or `{"error": "<message>"}` (raises with that message)."""
    mock = _load_github_write_mock()
    if mock is not None:
        raw = mock.get("update", {}).get(str(comment_id), {})
        if isinstance(raw, dict) and "error" in raw:
            raise ValueError(f"unable to update PR comment {comment_id}: {raw['error']}")
        return
    encoded_repo_parts = "/".join(quote(part, safe="") for part in repo.split("/", 1))
    argv = ["gh", "api", f"repos/{encoded_repo_parts}/issues/comments/{comment_id}", "--method", "PATCH"]
    _run_gh_write(argv, {"body": body}, tmp_prefix="agentic-sdlc-gh-comment-update-", verb=f"update PR comment {comment_id}")


def fetch_pr_comment(repo: str, comment_id: int) -> dict[str, Any]:
    """`GET repos/<repo>/issues/comments/<comment_id>` -- used only for the
    post-create/post-update re-fetch-and-verify step (`gate_status.py`
    section 3). Mock convention: `mock["fetch"][str(comment_id)]` is the raw
    comment object."""
    mock = _load_github_write_mock()
    if mock is not None:
        raw = mock.get("fetch", {}).get(str(comment_id))
        if not isinstance(raw, dict):
            raise ValueError(f"mocked fetch response for comment {comment_id} must be a JSON object")
        return raw
    encoded_repo_parts = "/".join(quote(part, safe="") for part in repo.split("/", 1))
    result = _run_gh(["gh", "api", f"repos/{encoded_repo_parts}/issues/comments/{comment_id}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        raise ValueError(f"unable to fetch PR comment {comment_id} for {repo}: {detail}")
    raw = _parse_gh_json(result.stdout, "fetch_pr_comment")
    if not isinstance(raw, dict):
        raise ValueError("GitHub PR comment fetch response must be a JSON object")
    return raw
