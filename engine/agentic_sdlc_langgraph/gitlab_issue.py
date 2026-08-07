"""GitLab issue linkage for G1 Intent / G2 Requirements Baseline.

Ported close to unchanged from `agentic_sdlc.py` (no project-overlay
dependency at all, same as `github_approval.py`):

- `GITLAB_ISSUE_URI` / `parse_gitlab_issue_uri` (kernel ~104-112 / ~514-518)
- `fetch_gitlab_issue` (kernel ~528-558), including the exact
  `AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE` env-var mocking convention the
  kernel test suite uses, so tests here can run with zero network/`glab`
  dependency.

Deliberately NOT an approval adapter, and deliberately NOT wired through
`resume_gate_with_*`/`Command(resume=...)` the way `github_approval.py` is:
linking a GitLab issue records where a task's intent/requirements content
came from, not a human's sign-off on it, and G1/G2's `human_approval_{gate}`
interrupt is unrelated to this. There is also no equivalent of
`github_review_to_approval` here -- an issue link produces no `Approval`,
only a plain URI string consumed by `cli.py`'s `plan` (see that module) to
seed `SDLCState.intent_record_id` / `requirements_baseline_id` once, at
plan time, the same way `--task` seeds `state["scope"]`.

Scope note (asymmetric with the kernel on purpose): the kernel additionally
attaches a gate-level `evidence_refs` entry when linking an issue
(`record_gitlab_issue_link` in `agentic_sdlc.py`). This package does not --
`GateState.evidence_refs` is populated generically by `graph.py`'s
`gate_decision_{gate_id}` from `agent_outputs`, and a plan-time-seeded
issue link is not an agent output, so reproducing that here would mean
special-casing `graph.py`'s gate-decision node for G1/G2, which this
package's design deliberately avoids (see `cli.py`'s `plan` docstring for
why: no changes to the dispatch/model-call path). `intent_record_id` /
`requirements_baseline_id` alone are still exported into the run record
either way.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

GITLAB_ISSUE_URI = re.compile(
    r"^gitlab-issue:(?P<project_path>[A-Za-z0-9_./-]+):issues/(?P<iid>\d+)$"
)

# Mocking convention for `requirement_issues.py`'s four GitLab-write/search
# functions below, mirroring `AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE` /
# `AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE`. Unlike those (one call, one
# fixed response), a `create-requirement-issues` run makes several distinct
# calls (identity check, per-item search, per-item create, per-item
# verification fetch) against one shared mock file, so the file is a single
# JSON object multiplexing all of them:
#
#   {
#     "identity": {"username": "svc-agentic-sdlc"},
#     "search": {"<labels joined by ',' in call order>": [ <raw issue>, ... ]},
#     "create": {"<labels joined by ',' in call order>": {"iid": 57, ...}},
#     "verify": {"<iid as string>": { <raw glab `issues/:iid` response> }}
#   }
#
# `search`/`create` are keyed by the exact `",".join(labels)` string the
# caller passed (`requirement_issues.py` always calls both with
# `[FIXED_LABEL, ITEM_LABEL]`, in that order, so tests can predict the
# key). `verify`'s raw response is run through the same
# raw-response-to-verification-shape extraction as a real `glab api`
# response would be -- the mock only replaces "how did we obtain the raw
# JSON", never the extraction logic, matching this module's existing
# `fetch_gitlab_issue` convention.
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
    # Explicit cwd in a private neutral temp dir so no git remote in this
    # repo's own cwd is ever discoverable by `glab` porcelain; explicit
    # timeout, argv list (never shell=True), no secrets on argv.
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
            # Covers FileNotFoundError (glab not installed/on PATH) and
            # any other failure to launch the subprocess. Deliberately
            # does not include `cwd` (a private temp directory path) in
            # the message.
            raise _glab_launch_error(argv, "failed to start", exc) from exc


def _glab_launch_error(argv: list[str], verb: str, exc: BaseException) -> ValueError:
    command = " ".join(argv[:2]) if len(argv) >= 2 else (argv[0] if argv else "glab")
    return ValueError(f"`{command}` {verb}: {exc.__class__.__name__} -- is glab installed and reachable?")


def _parse_glab_json(raw_stdout: bytes, context: str):
    """`json.loads(result.stdout)` for a `glab api` call that already
    exited 0. A 0 exit code does not guarantee well-formed JSON on
    stdout -- a warning banner mixed into stdout, a truncated write, or a
    future `glab` version change could all produce non-JSON/partial
    output. This must abort cleanly the same way a nonzero exit code
    does, not raise an unhandled `json.JSONDecodeError`.
    """
    try:
        return json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context}: glab exited 0 but stdout was not valid JSON ({exc})") from exc


def parse_gitlab_issue_uri(value: str) -> dict[str, str] | None:
    """Port of `agentic_sdlc.py`'s `parse_gitlab_issue_uri`."""
    match = GITLAB_ISSUE_URI.fullmatch(value)
    if not match:
        return None
    return match.groupdict()


def fetch_gitlab_issue(project_path: str, issue_iid: int) -> dict[str, Any]:
    """Port of `agentic_sdlc.py`'s `fetch_gitlab_issue`. No author/assignee
    identity is ever read here -- an issue link has no approver concept, so
    there is nothing to minimize away; only the fields needed to identify
    and reference the issue are kept.

    When `AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE` is set, reads a JSON object
    from that file instead of shelling out to `glab api` -- the exact
    mocking convention the kernel test suite uses, ported verbatim so tests
    here need neither network access nor a `glab` binary.
    """
    mock_path = os.environ.get("AGENTIC_SDLC_TEST_GITLAB_ISSUE_FILE")
    if mock_path:
        raw_response = json.loads(Path(mock_path).read_text(encoding="utf-8"))
    else:
        # Brought in line with this module's later-added hardened
        # pattern (`_run_glab`): explicit timeout, private neutral cwd,
        # and a clean abort on a nonzero exit code, launch failure
        # (missing `glab` binary), timeout, or malformed JSON on stdout,
        # rather than an unhandled traceback for any of those.
        encoded_project = quote(project_path, safe="")
        result = _run_glab(["glab", "api", f"projects/{encoded_project}/issues/{issue_iid}"])
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
            raise ValueError(f"unable to fetch GitLab issue for {project_path} issue {issue_iid}: {detail}")
        raw_response = _parse_glab_json(result.stdout, "fetch_gitlab_issue")
    if not isinstance(raw_response, dict):
        raise ValueError("GitLab issue API response must be a JSON object")
    title = raw_response.get("title")
    state = raw_response.get("state")
    if not isinstance(title, str) or not title:
        raise ValueError(f"GitLab issue {project_path}#{issue_iid} response is missing a title")
    if state not in {"opened", "closed"}:
        raise ValueError(f"GitLab issue {project_path}#{issue_iid} response has an unrecognized state: {state!r}")
    return {
        "iid": issue_iid,
        "title": title,
        "state": state,
        "web_url": raw_response.get("web_url"),
        "updated_at": raw_response.get("updated_at"),
    }


def gitlab_issue_uri(project_path: str, issue_iid: int) -> str:
    """Build and validate the `gitlab-issue:` URI for an already-fetched
    issue, mirroring the kernel's own parse-your-own-output discipline in
    `record_gitlab_issue_link`."""
    uri = f"gitlab-issue:{project_path}:issues/{issue_iid}"
    if parse_gitlab_issue_uri(uri) is None:
        raise ValueError(f"invalid GitLab issue URI components for {uri}")
    return uri


def resolve_issue_reference(value: str | None) -> str | None:
    """Parse a `<project-path>#<iid>` reference (the `--intent-gitlab-issue`
    / `--requirements-gitlab-issue` CLI flag shape, and `CreateTaskRequest`'s
    equivalent fields in `service.py`), fetch the issue, and return its
    validated `gitlab-issue:...` URI -- or `None` if `value` is `None`.
    Shared by `cli.py` and `service.py` so both surfaces parse/fetch/build
    the URI identically. Raises `ValueError` on a malformed reference or an
    unfetchable/invalid issue; callers translate that into their own
    surface's error shape."""
    if value is None:
        return None
    project_path, separator, iid_text = value.rpartition("#")
    if not separator or not project_path or not iid_text.isdigit():
        raise ValueError(f"GitLab issue reference must be in <project-path>#<iid> form, got {value!r}")
    issue = fetch_gitlab_issue(project_path, int(iid_text))
    return gitlab_issue_uri(project_path, issue["iid"])


# --------------------------------------------------------------------------
# `create-requirement-issues` GitLab calls (requirement_issues.py). See
# `ISSUE_CREATE_MOCK_ENV_VAR`'s docstring above for the shared mock-file
# shape. Deliberately separate from `fetch_gitlab_issue`/its callers above:
# see `fetch_gitlab_issue_verification`'s own docstring for why it is not a
# widening of `fetch_gitlab_issue`.
# --------------------------------------------------------------------------


def verify_gitlab_identity(expected_username: str) -> str:
    """Call `glab api user`, assert the authenticated `username` matches
    `expected_username` case-insensitively. Raises `ValueError` on
    mismatch or any subprocess/parse failure. Returns the verified
    username on success -- callers use this, not `expected_username`
    itself, as the recorded/compared identity from here on, since it is
    the one actually confirmed against the live credential."""
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
    """`GET projects/<enc>/issues?labels=<...>&state=all&per_page=20`.

    `state=all` is required -- omitting it defaults to open-only and would
    cause a duplicate create against an already-reused-but-closed issue.
    Label filter only -- never GitLab's free-text `search=` parameter,
    which matches model-controlled body text and would reopen the exact
    forgery vector the label anchor exists to close.
    """
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


def create_gitlab_issue(project_path: str, title: str, description: str, labels: list[str]) -> int:
    """`POST projects/<enc>/issues`, request body from a temp file.

    `glab api` mirrors `gh api`'s `--input <file>` convention (verified at
    implementation time against `glab`'s own CLI help where possible; see
    the task report for what this environment could and could not verify
    directly, since no `glab` binary was available to probe). The body is
    written to a 0600 file inside a private `mkdtemp` directory (POSIX
    `mkdtemp` already creates it `0700`), unlinked in a `finally` block --
    never passed via argv string. Returns the created issue's `iid`.
    """
    key = ",".join(labels)
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("create", {}).get(key)
        if not isinstance(raw, dict):
            raise ValueError(f"mocked create response for labels {key!r} must be a JSON object")
    else:
        encoded_project = quote(project_path, safe="")
        body = json.dumps({"title": title, "description": description, "labels": labels}).encode("utf-8")
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
                # Deliberately raised inside the `finally`-protected block
                # above (body file is still cleaned up either way) and
                # deliberately does not mention `body_path`/`tmp_dir`.
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


def fetch_gitlab_issue_verification(project_path: str, iid: int) -> dict[str, Any]:
    """Deliberately a SEPARATE function from `fetch_gitlab_issue`, not a
    widening of it. `fetch_gitlab_issue`'s docstring records a deliberate
    minimization decision (no author/assignee identity is ever read,
    because a source-link fetch has no approver concept to protect
    against). Widening that function in place would silently repeal that
    decision for its existing callers. This function returns exactly what
    post-creation verification needs and nothing more:
    `{iid, title, state, labels, assignee_count, confidential,
    project_path, author_username, web_url}`. `assignee_count` is an int
    (whether assignees exist), never assignee identities.
    `author_username` exists solely to verify the bot-identity control
    per-issue, and is itself a machine identity the operator supplied.

    The mocked path and the real (`glab api`) path share the exact same
    raw-response-to-verification-shape extraction below -- the mock only
    replaces "how did we obtain the raw JSON", matching this module's
    `fetch_gitlab_issue` convention.
    """
    mock = _load_issue_create_mock()
    if mock is not None:
        raw = mock.get("verify", {}).get(str(iid))
        if not isinstance(raw, dict):
            raise ValueError(f"mocked verification response for iid {iid} must be a JSON object")
    else:
        encoded_project = quote(project_path, safe="")
        result = _run_glab(["glab", "api", f"projects/{encoded_project}/issues/{iid}"])
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown glab api failure"
            raise ValueError(
                f"unable to fetch GitLab issue verification for {project_path} issue {iid}: {detail}"
            )
        raw = _parse_glab_json(result.stdout, "fetch_gitlab_issue_verification")
        if not isinstance(raw, dict):
            raise ValueError("GitLab issue verification response must be a JSON object")

    labels = raw.get("labels")
    labels = list(labels) if isinstance(labels, list) else []
    assignees = raw.get("assignees")
    assignee_count = len(assignees) if isinstance(assignees, list) else 0
    author = raw.get("author")
    author_username = author.get("username") if isinstance(author, dict) else None

    # Real GitLab issue responses have no direct "project_path" field;
    # derive it from `references.full` ("group/project#57"). Mocked
    # fixtures may supply "project_path" directly for readability -- both
    # are honored, direct field wins if present.
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
        "confidential": bool(raw.get("confidential", False)),
        "project_path": project_path_field,
        "author_username": author_username,
        "web_url": raw.get("web_url"),
    }
