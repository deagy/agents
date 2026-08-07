"""GitHub issue *write*/verify helpers for `create-github-gate-issues` /
`list-github-gate-issues` (`agentic_sdlc/gate_issues_github.py`).

**Unverified-assumption module -- read before trusting any of the following
"documented as fact" statements.** No live GitHub API verification session
was available while writing this module (no scratch-repo credentials; see
`roster/shared/agent-autonomy.yaml`'s `shared_system_access` gating in the
task that produced this file). Three specific assumptions below (V3, V4, V5)
are implemented *as if verified*, fail-closed, but are NOT independently
confirmed against a live `gh`/GitHub API response the way, say,
`gitlab_write.py`'s ported functions were validated against the LangGraph
engine's own working GitLab integration. Treat every "GitHub does X" claim
in this module's docstrings the same way `gitlab_write._is_link_unavailable_error`'s
own docstring already treats its stderr-format assumption: as an documented,
narrowly-scoped limitation, not a verified fact.

- **V3 (existence query)**: `state=all` is assumed to be accepted together
  with `labels=` on `GET /repos/{owner}/{repo}/issues`. If this turns out to
  be rejected by the live API, the documented fallback (not implemented here)
  is two separate calls -- `state=open` and `state=closed` -- unioned by the
  caller; implementing that fallback now would be premature given it cannot
  be exercised against a live response either.
- **V4 (label auto-creation)**: it is unverified whether GitHub's issue-create
  endpoint auto-creates missing labels. `ensure_label()` below is a defensive
  `POST /repos/{repo}/labels` step (422 "already_exists" treated as success)
  that runs before every issue creation regardless of whether auto-creation
  turns out to be true -- cheap insurance either way, and it removes any hard
  dependency on the unverified behavior.
- **V5 (secondary rate limit signature)**: `_is_secondary_rate_limit_error`
  pattern-matches on GitHub's documented secondary-rate-limit message text
  ("secondary rate limit"). The exact stderr shape `gh api` wraps that text
  in has not been observed live in this task; the function is written to be
  robust to surrounding text (a case-insensitive substring match), but is
  still an assumption about the underlying message, not a captured fixture
  from a real throttled response.

## Idempotency query: marker label alone, never the Search API

`search_issues_by_label()` below queries by the marker label ALONE (not a
`[FIXED_LABEL, own_label]` pair the way `gitlab_write.search_gitlab_issues_by_labels`
does) -- GitHub's `labels=` query parameter on the issue-list endpoint
already ANDs every comma-separated label together file-side when more than
one is given, but this module deliberately sends only the fine-grained
marker label; `gate_issues_github.py`'s post-processing step (never this
module) is responsible for validating the `FIXED_LABEL` anchor is *also*
present on any match, exactly mirroring `gate_issues.py`'s
`_validate_matched_issue`.

This module and `gate_issues_github.py` never call GitHub's Search API
(GitHub's full-text issue-search endpoint) -- deliberately rejected per the task's design
(ambiguity/staleness/rate-limit-cost tradeoffs of a full-text search index
versus a direct label-filtered list call). See
`test_gate_issues_github.py`'s source-inspection test asserting neither
module contains the literal search-endpoint path fragments this module must never call.

## Case-insensitive label comparison (deviation from `gitlab_write.py`)

GitHub label names are unique on a repository case-insensitively (creating
`Agentic-SDLC` when `agentic-sdlc` already exists is rejected/merged
server-side), unlike `gate_issues.py`'s exact-match set comparison against
GitLab labels. `gate_issues_github.py`'s post-processing lowercases every
label before comparing -- this module returns labels/logins exactly as
GitHub's API returns them (no case normalization at this layer) so the
comparison decision stays visible at the call site.

## Mock-file convention

`GITHUB_ISSUE_MOCK_ENV_VAR` multiplexes every canned response for this
module under one JSON file, top-level keys `search`/`create`/`verify`/
`assignee_update`/`repo`/`labels` -- deliberately distinct from
`github_write.GITHUB_READ_MOCK_ENV_VAR` (`AGENTIC_SDLC_TEST_GITHUB_READ_FILE`,
used for the identity/collaborator/user-exists pre-checks this module's
caller also needs), matching `github_status_write.py`'s existing precedent
of splitting read-mock and write-mock env vars per feature rather than
reusing one global mock file for every GitHub-touching module in this
package.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

# Locally defined, not cross-imported from gitlab_write.FIXED_LABEL -- see
# gate_issues_github.py's module docstring and test_gate_issues_github.py's
# PortIntegrityTests-equivalent parity test asserting equality anyway.
FIXED_LABEL = "agentic-sdlc"

GITHUB_ISSUE_MOCK_ENV_VAR = "AGENTIC_SDLC_TEST_GITHUB_ISSUE_FILE"

# Applied (via delay_between_mutations()) between mutative gh api calls only
# -- never before the first mutative call of a run, never between reads,
# never during --dry-run. Callers (gate_issues_github.py) own call-ordering
# and decide when this is invoked; see module docstring's V5 entry.
WRITE_DELAY_SECONDS = 1.0

_GH_TIMEOUT_SECONDS = 30


class SecondaryRateLimitError(ValueError):
    """Raised when a mutative `gh api` call's stderr matches GitHub's
    documented secondary-rate-limit signature (see module docstring's V5
    entry). Callers must not retry, back off, or partially continue --
    `gate_issues_github.py` maps this to a `secondary-rate-limit` block
    (CLI exit 2) and aborts the run immediately."""


def _load_issue_mock() -> dict[str, Any] | None:
    mock_path = os.environ.get(GITHUB_ISSUE_MOCK_ENV_VAR)
    if not mock_path:
        return None
    payload = json.loads(Path(mock_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{GITHUB_ISSUE_MOCK_ENV_VAR} must contain a JSON object")
    return payload


def _run_gh(argv: list[str]) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-gh-issue-") as cwd:
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


def _encode_repo(repo: str) -> str:
    return "/".join(quote(part, safe="") for part in repo.split("/", 1))


def _is_secondary_rate_limit_error(stderr_text: str) -> bool:
    """Pure substring check factored out so it can be unit tested directly
    without a live `gh` binary (see module docstring's V5 entry). Matches
    GitHub's documented secondary-rate-limit message text, case-insensitive,
    anywhere in the `gh api` error output."""
    return "secondary rate limit" in stderr_text.lower()


def _is_label_already_exists_error(stderr_text: str) -> bool:
    """Pure substring check: GitHub's create-label endpoint returns HTTP 422
    with an `already_exists` error code when the label already exists (see
    module docstring's V4 entry) -- `gh api` surfaces this as plain text in
    stderr, the same limitation documented on `gitlab_write._is_link_unavailable_error`."""
    lowered = stderr_text.lower()
    return "422" in stderr_text and "already_exists" in lowered


def _run_gh_write(argv: list[str], body_payload: dict[str, Any] | None, *, tmp_prefix: str, verb: str) -> bytes:
    """Shared helper for POST/PATCH calls: writes `body_payload` (if any) to
    a `0600` same-filesystem temp file and passes it via `--input <path>`,
    mirroring `gitlab_write.create_gitlab_issue`'s convention exactly.
    Raises `SecondaryRateLimitError` (never retried/backed-off) when the
    failure stderr matches the secondary-rate-limit signature."""
    tmp_dir = tempfile.mkdtemp(prefix=tmp_prefix)
    try:
        full_argv = list(argv)
        if body_payload is not None:
            body = json.dumps(body_payload).encode("utf-8")
            fd, body_path = tempfile.mkstemp(dir=tmp_dir, prefix="body-", suffix=".json")
            try:
                os.write(fd, body)
            finally:
                os.close(fd)
            os.chmod(body_path, 0o600)
            full_argv = full_argv + ["--input", body_path]
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
        if _is_secondary_rate_limit_error(detail):
            raise SecondaryRateLimitError(f"unable to {verb}: secondary rate limit hit: {detail}")
        raise ValueError(f"unable to {verb}: {detail}")
    return result.stdout


def delay_between_mutations() -> None:
    """Sleep `WRITE_DELAY_SECONDS`. Callers (`gate_issues_github.py`) invoke
    this themselves between consecutive mutative calls of the same run --
    never before the first mutative call, never between reads, never during
    `--dry-run`. Kept as an explicit, separately callable/mockable step
    rather than embedded inside each write function so call-count/ordering
    stays the orchestrator's responsibility, not this module's."""
    time.sleep(WRITE_DELAY_SECONDS)


def fetch_github_repo(repo: str) -> dict[str, Any]:
    """`GET /repos/{owner}/{repo}` -- the pre-flight this feature adds beyond
    GitLab parity (see `gate_issues_github.py` module docstring). Returns
    the raw response object; callers read `has_issues`/`private` directly.
    Mock convention: `mock["repo"]` is the raw response object."""
    mock = _load_issue_mock()
    if mock is not None:
        raw = mock.get("repo")
        if not isinstance(raw, dict):
            raise ValueError("mocked repo response must be a JSON object")
        return raw
    result = _run_gh(["gh", "api", f"repos/{_encode_repo(repo)}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        raise ValueError(f"unable to fetch repository {repo}: {detail}")
    raw = _parse_gh_json(result.stdout, "fetch_github_repo")
    if not isinstance(raw, dict):
        raise ValueError("GitHub repository response must be a JSON object")
    return raw


def ensure_label(repo: str, label_name: str) -> None:
    """`POST /repos/{repo}/labels`. Defensive insurance against the
    unverified V4 assumption (see module docstring) -- runs before every
    issue creation regardless of whether GitHub turns out to auto-create
    missing labels. A 422 "already_exists" response is treated as success,
    never an error. Mock convention: `mock["labels"][label_name]` is either
    absent/any non-error object (success) or `{"error_status": 422,
    "error": "already_exists ..."}` / other status (raises)."""
    mock = _load_issue_mock()
    if mock is not None:
        raw = mock.get("labels", {}).get(label_name)
        if isinstance(raw, dict) and "error_status" in raw:
            status = raw["error_status"]
            detail = f"HTTP {status}: {raw.get('error', 'no detail')}"
            if status == 422 and "already_exists" in str(raw.get("error", "")).lower():
                return
            raise ValueError(f"unable to ensure label {label_name!r} on {repo}: {detail}")
        return
    argv = ["gh", "api", f"repos/{_encode_repo(repo)}/labels", "--method", "POST"]
    body_payload = {"name": label_name, "color": "ededed"}
    tmp_dir = tempfile.mkdtemp(prefix="agentic-sdlc-gh-label-")
    try:
        body = json.dumps(body_payload).encode("utf-8")
        fd, body_path = tempfile.mkstemp(dir=tmp_dir, prefix="body-", suffix=".json")
        try:
            os.write(fd, body)
        finally:
            os.close(fd)
        os.chmod(body_path, 0o600)
        result = subprocess.run(
            argv + ["--input", body_path], cwd=tmp_dir, capture_output=True, timeout=_GH_TIMEOUT_SECONDS, check=False
        )
    finally:
        for entry in Path(tmp_dir).glob("body-*"):
            entry.unlink(missing_ok=True)
        Path(tmp_dir).rmdir()
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        if _is_label_already_exists_error(detail):
            return
        if _is_secondary_rate_limit_error(detail):
            raise SecondaryRateLimitError(f"unable to ensure label {label_name!r} on {repo}: {detail}")
        raise ValueError(f"unable to ensure label {label_name!r} on {repo}: {detail}")


def search_issues_by_label(repo: str, label: str) -> list[dict[str, Any]]:
    """`GET /repos/{owner}/{repo}/issues?labels=<label>&state=all&per_page=20`
    -- the marker label ALONE, never a label pair, never `--paginate`, never
    the Search API (see module docstring). Mock convention:
    `mock["search"][label]` is the raw issue array."""
    mock = _load_issue_mock()
    if mock is not None:
        raw = mock.get("search", {}).get(label, [])
        if not isinstance(raw, list):
            raise ValueError(f"mocked search response for label {label!r} must be a JSON array")
        return raw
    label_param = quote(label, safe="")
    result = _run_gh(
        ["gh", "api", f"repos/{_encode_repo(repo)}/issues?labels={label_param}&state=all&per_page=20"]
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        raise ValueError(f"unable to search GitHub issues in {repo} for label {label!r}: {detail}")
    raw = _parse_gh_json(result.stdout, "search_issues_by_label")
    if not isinstance(raw, list):
        raise ValueError("GitHub issue search response must be a JSON array")
    return raw


def create_issue(repo: str, title: str, body: str, labels: list[str], assignees: list[str] | None = None) -> int:
    """`POST /repos/{repo}/issues`. Mock convention:
    `mock["create"][",".join(labels)]` is `{"number": <int>}`."""
    key = ",".join(labels)
    mock = _load_issue_mock()
    if mock is not None:
        raw = mock.get("create", {}).get(key)
        if not isinstance(raw, dict):
            raise ValueError(f"mocked create response for labels {key!r} must be a JSON object")
    else:
        body_payload: dict[str, Any] = {"title": title, "body": body, "labels": labels}
        if assignees:
            body_payload["assignees"] = list(assignees)
        stdout = _run_gh_write(
            ["gh", "api", f"repos/{_encode_repo(repo)}/issues", "--method", "POST"],
            body_payload,
            tmp_prefix="agentic-sdlc-gh-issue-create-",
            verb=f"create GitHub issue in {repo}",
        )
        raw = _parse_gh_json(stdout, "create_issue")
        if not isinstance(raw, dict):
            raise ValueError("GitHub issue create response must be a JSON object")

    number = raw.get("number")
    if not isinstance(number, int):
        raise ValueError("GitHub issue create response is missing an integer 'number'")
    return number


def _extract_verification(raw: dict[str, Any], number: int) -> dict[str, Any]:
    labels_raw = raw.get("labels")
    labels: list[str] = []
    if isinstance(labels_raw, list):
        for entry in labels_raw:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                labels.append(entry["name"])
            elif isinstance(entry, str):
                labels.append(entry)

    assignees_raw = raw.get("assignees")
    assignees = [
        entry.get("login")
        for entry in (assignees_raw if isinstance(assignees_raw, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("login"), str)
    ]

    user = raw.get("user")
    author_login = user.get("login") if isinstance(user, dict) else None

    repository_url = raw.get("repository_url")
    repo_from_url = None
    if isinstance(repository_url, str):
        parts = repository_url.rstrip("/").split("/")
        if len(parts) >= 2:
            repo_from_url = f"{parts[-2]}/{parts[-1]}"

    return {
        "number": number,
        "title": raw.get("title"),
        "state": raw.get("state"),
        "labels": labels,
        "assignees": assignees,
        "author_login": author_login,
        "repo_from_url": repo_from_url,
        "has_pull_request_key": "pull_request" in raw,
        "html_url": raw.get("html_url"),
    }


def fetch_issue_verification(repo: str, number: int) -> dict[str, Any]:
    """`GET /repos/{repo}/issues/{number}`. Returns
    `{number, title, state, labels, assignees, author_login, repo_from_url,
    has_pull_request_key, html_url}` -- `labels`/`assignees` are returned
    exactly as GitHub's API returns them (no case normalization; see module
    docstring). Mock convention: `mock["verify"][str(number)]` is the raw
    issue response object."""
    mock = _load_issue_mock()
    if mock is not None:
        raw = mock.get("verify", {}).get(str(number))
        if not isinstance(raw, dict):
            raise ValueError(f"mocked verification response for issue {number} must be a JSON object")
        return _extract_verification(raw, number)
    result = _run_gh(["gh", "api", f"repos/{_encode_repo(repo)}/issues/{number}"])
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "unknown gh api failure"
        raise ValueError(f"unable to fetch GitHub issue {repo}#{number}: {detail}")
    raw = _parse_gh_json(result.stdout, "fetch_issue_verification")
    if not isinstance(raw, dict):
        raise ValueError("GitHub issue fetch response must be a JSON object")
    return _extract_verification(raw, number)


def update_issue_assignees(repo: str, number: int, assignees: list[str]) -> None:
    """`PATCH /repos/{repo}/issues/{number}` with `assignees`. Only ever
    called behind `--reconcile-assignees`. Mock convention:
    `mock["assignee_update"][str(number)]` is either any JSON object
    (success) or `{"error": "<message>"}` (raises)."""
    mock = _load_issue_mock()
    if mock is not None:
        raw = mock.get("assignee_update", {}).get(str(number), {})
        if isinstance(raw, dict) and "error" in raw:
            raise ValueError(f"unable to update assignees for issue {number}: {raw['error']}")
        return
    _run_gh_write(
        ["gh", "api", f"repos/{_encode_repo(repo)}/issues/{number}", "--method", "PATCH"],
        {"assignees": list(assignees)},
        tmp_prefix="agentic-sdlc-gh-issue-assignee-",
        verb=f"update assignees for issue {repo}#{number}",
    )
