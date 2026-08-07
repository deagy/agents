"""`publish-gate-status` / `list-gate-status`: post (and idempotently update
in place on re-run) a one-way, read-only gate-status summary comment on a
task's GitHub PR or GitLab MR.

## Strictly one-way, never approval evidence

This comment is diagnostics for humans watching a PR/MR, nothing else.
`agentic-sdlc` never reads it, its reactions, or its replies back into gate
state -- there is no "approve-from-gate-status-comment" adapter and there
never will be; gate approval remains exclusively `agentic-sdlc decide` /
`approve-from-gitlab-mr` / `approve-from-github-pr`, against an external
approval record. The rendered body says so explicitly (see
`_ADVISORY_PARAGRAPH` below) so a reader cannot mistake it for a sign-off
surface. This module never calls a reactions/award-emoji endpoint and never
persists reaction data (see `test_gate_status.py`'s `NoInjectionSurface`-style
tests).

## Data minimization -- content comes from exactly two sources

1. `agentic_sdlc.gate_status_projection()`'s return value (a pure,
   read-only projection of `run-record.json`: `task_id`, `current_phase`,
   the ten gates' `{gate_id, status, applicability, required_reentry_gate}`,
   `re_entry_history`, and `classification` -- see that function's own
   docstring in `agentic_sdlc/__init__.py`).
2. The bundled `contracts/lifecycle-gates.json` (gate names, `human_only`).

This module never opens `authorities.json` and never imports
`record_github_approval`, `record_gitlab_approval`, `record_gate_decision`,
or `record_gitlab_issue_link` from the parent package -- see
`test_gate_status.py`'s `OrthogonalityTests` for the same source-inspection
+ file-untouched proof pattern `gate_issues.py`'s own `OrthogonalityTests`
uses. `re_entry_history` is reduced to a count plus the earliest re-entered
gate id only (`_earliest_reentered_gate`) -- `actor`/`reason` (real-identity
and free-text fields) are never rendered, and `classification` is used only
for the one `--allow-classification` equality check, never rendered.

Because every rendered token is either fixed template text, a closed-enum
value (gate id, gate status, applicability, current phase), a bundled
contract's gate name, a 16-hex hash, an RFC-3339 timestamp, or a small
integer, this module has NO free-text injection surface at all -- unlike
`gate_issues.py`, there is no `sanitize_free_text`/`sanitize_title_text`
machinery here, and there must never be, because nothing here is ever
project-supplied free text (see `test_gate_status.py`'s
`ContentWhitelistTests`).

## Marker and matching (spec-mandated formula)

`compute_status_marker(task_id) = sha256("gate-status\\x00" + task_id)[:16]`
-- domain-separated from `gate_issues.py`'s `compute_gate_marker`/
`compute_approval_marker` (see that module's own marker table, which this
module's marker is also listed in). Embedded in the comment body as
`<!-- agentic-sdlc:gate-status:v1:<marker> -->`; matching is on the
`<marker>` token only, never the `v1` version segment, so a future v2
template still finds and updates a v1 comment rather than posting a
duplicate (`_MARKER_PATTERN_TEMPLATE` below matches any `v\\d+`).

The *displayed* task hash (`` `**Lifecycle gate status — task `<hash>`**` ``
in the rendered body) is a **different** value: `gate_issues.task_hash`
(`sha256(task_id)[:16]`, no domain-separation prefix). These are
deliberately two distinct hashes serving two distinct purposes (matching
token vs. human-readable display); see this task's completion report for
the explicit call-out of this as a documented judgment call.

## Idempotency classification (spec section 3)

`run()` always lists comments/notes (paginated, `MAX_COMMENT_PAGES = 10` /
`PER_PAGE = 100`, i.e. up to 1000) and verifies `--as-bot` identity in BOTH
`--dry-run` and `--apply` mode -- both are read-only forge calls, needed to
report an accurate `create`/`update`/`unchanged`/`blocked` classification
even in dry-run. Only `--apply` may ever call `create_comment`/
`update_comment`. Exceeding the page cap always raises `GateStatusBlocked`
(in both modes): unlike an ambiguous match or a foreign-authored comment
(which dry-run can safely *report* as `action: "blocked"` without raising,
since nothing unsafe happens by merely computing that diagnosis), the page
cap means the classification itself cannot be trusted -- there might be a
matching comment on an unfetched page, so this module refuses to even guess
at any point.

## Ledger (diagnostics only, forge-qualified, never trusted for existence)

`<root>/.agentic-sdlc/runs/<task_id>/gate-status-<forge>.json` +
`.lock` -- a distinct file family from `gate_issues.py`'s
`gate-issues-<forge>.json`, so no collision. Both share the durable-write
and lock primitives factored out to `_forge_ledger.py`. Existence is always
determined by scanning the PR/MR's live comments for the marker, never by
trusting this ledger -- exactly like `gate_issues.py`'s GitLab-label search.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import CONTRACTS, GATE_IDS, OVERLAY, gate_status_projection, load_json, now
from . import _forge_ledger, gate_issues, github_status_write, gitlab_write

LEDGER_SCHEMA_VERSION = 1

FORGE_GITHUB = "github"
FORGE_GITLAB = "gitlab"
FORGES = (FORGE_GITHUB, FORGE_GITLAB)

TEMPLATE_VERSION = 1
MAX_COMMENT_PAGES = 10
PER_PAGE = 100

_MARKER_PATTERN_TEMPLATE = r"<!-- agentic-sdlc:gate-status:v\d+:{marker} -->"

_ADVISORY_PARAGRAPH = (
    "**This comment is not an approval and is never read back.**\n"
    'Approving this merge request, reacting to this comment, replying "LGTM", or\n'
    "closing anything linked from it does not approve any lifecycle gate.\n"
    "`agentic-sdlc` never reads this comment, its reactions, or its replies back\n"
    "into gate state — this render is strictly one-way. Gate approval is recorded\n"
    "only by `agentic-sdlc decide` or `agentic-sdlc approve-from-gitlab-mr` /\n"
    "`approve-from-github-pr`, against an external approval record. If anyone cites\n"
    "this comment as evidence that a gate is approved, they are mistaken."
)


class GateStatusError(ValueError):
    """Structural/policy failure -- CLI maps this to exit code 1."""


class GateStatusBlocked(ValueError):
    """Needs human resolution (ambiguous match, foreign author, page-cap
    exceeded, lock held, post-write verification mismatch) -- CLI maps this
    to exit code 2."""


# --------------------------------------------------------------------------
# Marker / hash
# --------------------------------------------------------------------------


def compute_status_marker(task_id: str) -> str:
    return hashlib.sha256(f"gate-status\x00{task_id}".encode("utf-8")).hexdigest()[:16]


def _marker_pattern(marker: str) -> re.Pattern[str]:
    return re.compile(_MARKER_PATTERN_TEMPLATE.format(marker=re.escape(marker)))


_RENDERED_AT_RE = re.compile(r"(?<=· rendered ).*")


def _canonicalize_for_comparison(body: str) -> str:
    """Blank the live `rendered_at` timestamp before comparing bodies for
    the unchanged/update classification -- `rendered_at` changes on every
    invocation by design (see render_gate_status_body) and must never by
    itself force an `update`. The body actually posted still carries the
    real timestamp; only the comparison is normalized."""
    return _RENDERED_AT_RE.sub("<omitted-for-comparison>", body)


# --------------------------------------------------------------------------
# Rendering (pure; no project-supplied free text ever enters this)
# --------------------------------------------------------------------------


def _earliest_reentered_gate(re_entry_history: list[dict[str, Any]]) -> str | None:
    candidates = [
        entry.get("earliest_gate")
        for entry in re_entry_history
        if isinstance(entry, dict) and entry.get("earliest_gate") in GATE_IDS
    ]
    if not candidates:
        return None
    return min(candidates, key=GATE_IDS.index)


def _status_cell(gate: dict[str, Any], *, human_only: bool) -> str:
    if gate.get("applicability") == "not-applicable":
        return "not applicable"
    required_reentry_gate = gate.get("required_reentry_gate")
    if required_reentry_gate is not None:
        return f"invalidated (re-entry required from {required_reentry_gate})"
    status = str(gate.get("status"))
    if human_only and status != "approved":
        return f"{status} (human-only gate)"
    return status


def render_gate_status_body(
    *, task_id: str, projection: dict[str, Any], lifecycle_contracts: dict[str, dict[str, Any]], rendered_at: str,
) -> str:
    marker = compute_status_marker(task_id)
    task_hash = gate_issues.task_hash(task_id)
    gate_by_id = {gate["gate_id"]: gate for gate in projection["gates"]}

    lines = [
        f"<!-- agentic-sdlc:gate-status:v{TEMPLATE_VERSION}:{marker} -->",
        "> Machine-generated by agentic-sdlc. Not a human-authored artifact. **Not approval evidence.**",
        "> Reacting or replying to this comment does not approve anything.",
        "",
        f"**Lifecycle gate status — task `{task_hash}`**",
        f"Current phase: {projection['current_phase']} · rendered {rendered_at}",
        "",
        "| Gate | Status |",
        "| --- | --- |",
    ]
    for gate_id in GATE_IDS:
        gate = gate_by_id[gate_id]
        contract = lifecycle_contracts.get(gate_id, {})
        gate_name = contract.get("name", gate_id)
        human_only = bool(contract.get("human_only"))
        lines.append(f"| {gate_id} {gate_name} | {_status_cell(gate, human_only=human_only)} |")
    lines.append("")

    re_entry_history = projection.get("re_entry_history", [])
    if re_entry_history:
        earliest = _earliest_reentered_gate(re_entry_history)
        lines.append(f"Re-entries recorded: {len(re_entry_history)} (earliest re-entered gate: {earliest})")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.extend(_ADVISORY_PARAGRAPH.split("\n"))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# ForgeAdapter protocol + concrete adapters
# --------------------------------------------------------------------------


class NormalizedComment(dict):
    """`{id, body, author, is_system}` -- the ONLY fields ever parsed out of
    a raw forge comment/note response. Never carries `reactions`,
    `award_emoji`, or any other field."""


def _parse_github_comment(raw: dict[str, Any]) -> NormalizedComment:
    user = raw.get("user")
    author = user.get("login") if isinstance(user, dict) else None
    return NormalizedComment(id=raw.get("id"), body=raw.get("body"), author=author, is_system=False)


def _parse_gitlab_note(raw: dict[str, Any]) -> NormalizedComment:
    author_obj = raw.get("author")
    author = author_obj.get("username") if isinstance(author_obj, dict) else None
    return NormalizedComment(id=raw.get("id"), body=raw.get("body"), author=author, is_system=bool(raw.get("system", False)))


class ForgeAdapter(Protocol):
    """Structural protocol implemented by `GithubForgeAdapter` and
    `GitlabForgeAdapter` below. Exactly the four methods the spec
    mandates."""

    def verify_identity(self, expected_username: str) -> str: ...

    def list_comments(self) -> list[NormalizedComment]: ...

    def create_comment(self, body: str) -> NormalizedComment: ...

    def update_comment(self, comment_id: Any, body: str) -> NormalizedComment: ...


@dataclass(frozen=True)
class GithubForgeAdapter:
    repo: str
    pr: int

    def verify_identity(self, expected_username: str) -> str:
        return github_status_write.verify_github_identity(expected_username)

    def list_comments(self) -> list[NormalizedComment]:
        comments: list[NormalizedComment] = []
        page = 1
        while page <= MAX_COMMENT_PAGES:
            raw_page = github_status_write.list_pr_comments(self.repo, self.pr, page=page, per_page=PER_PAGE)
            comments.extend(_parse_github_comment(item) for item in raw_page if isinstance(item, dict))
            if len(raw_page) < PER_PAGE:
                return comments
            page += 1
        raise GateStatusBlocked(
            f"more than {MAX_COMMENT_PAGES * PER_PAGE} comments on {self.repo}#{self.pr} -- cannot safely "
            "confirm whether a matching comment exists on a later page; refusing to create or update"
        )

    def create_comment(self, body: str) -> NormalizedComment:
        comment_id = github_status_write.create_pr_comment(self.repo, self.pr, body)
        return _parse_github_comment(github_status_write.fetch_pr_comment(self.repo, comment_id))

    def update_comment(self, comment_id: Any, body: str) -> NormalizedComment:
        github_status_write.update_pr_comment(self.repo, comment_id, body)
        return _parse_github_comment(github_status_write.fetch_pr_comment(self.repo, comment_id))


@dataclass(frozen=True)
class GitlabForgeAdapter:
    project_path: str
    mr_iid: int

    def verify_identity(self, expected_username: str) -> str:
        return gitlab_write.verify_gitlab_identity(expected_username)

    def list_comments(self) -> list[NormalizedComment]:
        notes: list[NormalizedComment] = []
        page = 1
        while page <= MAX_COMMENT_PAGES:
            raw_page = gitlab_write.list_mr_notes(self.project_path, self.mr_iid, page=page, per_page=PER_PAGE)
            notes.extend(_parse_gitlab_note(item) for item in raw_page if isinstance(item, dict))
            if len(raw_page) < PER_PAGE:
                return notes
            page += 1
        raise GateStatusBlocked(
            f"more than {MAX_COMMENT_PAGES * PER_PAGE} notes on {self.project_path} MR {self.mr_iid} -- cannot "
            "safely confirm whether a matching note exists on a later page; refusing to create or update"
        )

    def create_comment(self, body: str) -> NormalizedComment:
        note_id = gitlab_write.create_mr_note(self.project_path, self.mr_iid, body)
        return _parse_gitlab_note(gitlab_write.fetch_mr_note(self.project_path, self.mr_iid, note_id))

    def update_comment(self, comment_id: Any, body: str) -> NormalizedComment:
        gitlab_write.update_mr_note(self.project_path, self.mr_iid, comment_id, body)
        return _parse_gitlab_note(gitlab_write.fetch_mr_note(self.project_path, self.mr_iid, comment_id))


def _validate_forge_target(
    forge: str, repo: str | None, pr: int | None, project_path: str | None, mr_iid: int | None,
) -> None:
    if forge == FORGE_GITHUB:
        if repo is None or pr is None:
            raise GateStatusError("--forge github requires --repo and --pr")
        if project_path is not None or mr_iid is not None:
            raise GateStatusError("--project-path/--mr-iid must not be supplied with --forge github")
    elif forge == FORGE_GITLAB:
        if project_path is None or mr_iid is None:
            raise GateStatusError("--forge gitlab requires --project-path and --mr-iid")
        if repo is not None or pr is not None:
            raise GateStatusError("--repo/--pr must not be supplied with --forge gitlab")
    else:
        raise GateStatusError(f"unknown forge: {forge!r}")


def _build_adapter(
    forge: str, *, repo: str | None, pr: int | None, project_path: str | None, mr_iid: int | None,
) -> ForgeAdapter:
    if forge == FORGE_GITHUB:
        assert repo is not None and pr is not None
        return GithubForgeAdapter(repo=repo, pr=pr)
    assert project_path is not None and mr_iid is not None
    return GitlabForgeAdapter(project_path=project_path, mr_iid=mr_iid)


def _is_mocked(forge: str) -> bool:
    if forge == FORGE_GITHUB:
        return bool(os.environ.get(github_status_write.GITHUB_WRITE_MOCK_ENV_VAR))
    return bool(os.environ.get(gitlab_write.ISSUE_CREATE_MOCK_ENV_VAR))


# --------------------------------------------------------------------------
# Classification (spec section 3)
# --------------------------------------------------------------------------


def classify(
    matches: list[NormalizedComment], bot_username: str, rendered_body: str,
) -> tuple[str, str | None, NormalizedComment | None]:
    """Returns `(action, reason, matched_comment)`. `action` is one of
    `create`/`update`/`unchanged`/`blocked`."""
    if len(matches) == 0:
        return "create", None, None
    if len(matches) > 1:
        return "blocked", "multiple_matches", None
    comment = matches[0]
    author = comment.get("author") or ""
    if author.lower() != bot_username.lower():
        return "blocked", "foreign_author", comment
    if _canonicalize_for_comparison(comment.get("body") or "") == _canonicalize_for_comparison(rendered_body):
        return "unchanged", None, comment
    return "update", None, comment


# --------------------------------------------------------------------------
# Sidecar ledger (diagnostics only, never trusted for existence)
# --------------------------------------------------------------------------


def _ledger_path(root: Path, task_id: str, forge: str) -> Path:
    return _forge_ledger.ledger_path(Path(root), OVERLAY, task_id, f"gate-status-{forge}.json")


def _lock_path(root: Path, task_id: str, forge: str) -> Path:
    return _forge_ledger.lock_path(Path(root), OVERLAY, task_id, f"gate-status-{forge}.lock")


def _empty_ledger(task_id: str, forge: str) -> dict[str, Any]:
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "task_id": task_id,
        "forge": forge,
        "target": None,
        "bot_username": None,
        "mocked": False,
        "marker": None,
        "entries": [],
    }


def read_ledger(root: Path, task_id: str, forge: str) -> dict[str, Any]:
    path = _ledger_path(Path(root), task_id, forge)
    if not path.is_file():
        return _empty_ledger(task_id, forge)
    return json.loads(path.read_text(encoding="utf-8"))


def write_ledger(root: Path, task_id: str, ledger: dict[str, Any], forge: str) -> None:
    path = _ledger_path(Path(root), task_id, forge)
    _forge_ledger.write_ledger_file(path, ledger, tmp_prefix=".gate-status.")


def acquire_lock(root: Path, task_id: str, forge: str, *, break_lock: bool) -> Path:
    path = _lock_path(Path(root), task_id, forge)
    try:
        return _forge_ledger.acquire_lock_file(path, break_lock=break_lock)
    except _forge_ledger.LedgerLockHeld as exc:
        raise GateStatusBlocked(str(exc)) from None


def release_lock(path: Path) -> None:
    _forge_ledger.release_lock_file(path)


def list_ledgers(root: Path, task_id: str) -> dict[str, dict[str, Any]]:
    """`list-gate-status` has no `--forge` flag (a task may have been
    published to either or both forges over its lifetime) -- report both
    ledgers, zero network."""
    return {forge: read_ledger(root, task_id, forge) for forge in FORGES}


# --------------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------------


def run(
    *, root: Path, task_id: str, forge: str, as_bot: str, allow_classification: str | None, apply: bool,
    repo: str | None = None, pr: int | None = None, project_path: str | None = None, mr_iid: int | None = None,
    break_lock: bool = False, i_know_this_is_mocked: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    _validate_forge_target(forge, repo, pr, project_path, mr_iid)

    projection = gate_status_projection(root, task_id)
    if allow_classification is None or allow_classification != projection.get("classification"):
        raise GateStatusError(
            "--allow-classification must be supplied and exactly match the task's classification "
            f"(got {allow_classification!r}, task classification is {projection.get('classification')!r})"
        )

    lifecycle_contracts = {item["id"]: item for item in load_json(CONTRACTS / "lifecycle-gates.json")["gates"]}
    rendered_at = now()
    marker = compute_status_marker(task_id)
    body = render_gate_status_body(
        task_id=task_id, projection=projection, lifecycle_contracts=lifecycle_contracts, rendered_at=rendered_at,
    )

    adapter = _build_adapter(forge, repo=repo, pr=pr, project_path=project_path, mr_iid=mr_iid)
    mocked = _is_mocked(forge)

    try:
        verified_username = adapter.verify_identity(as_bot)
    except ValueError as exc:
        raise GateStatusError(str(exc)) from exc

    comments = adapter.list_comments()  # may raise GateStatusBlocked (page cap) -- unconditional, both modes
    pattern = _marker_pattern(marker)
    matches = [
        comment for comment in comments
        if not comment.get("is_system") and pattern.search(comment.get("body") or "")
    ]
    action, reason, matched = classify(matches, verified_username, body)

    summary = {
        "mode": "apply" if apply else "dry-run",
        "task_id": task_id,
        "task_hash": gate_issues.task_hash(task_id),
        "forge": forge,
        "marker": marker,
        "action": action,
        "reason": reason,
        "matched_comment_id": matched.get("id") if matched else None,
        "mocked": mocked,
        "body": body,
    }

    if not apply:
        # Dry-run never writes and never raises for an ambiguous/blocked
        # classification -- it only reports what an --apply run would do
        # (see module docstring's "Idempotency classification" section).
        return summary

    if mocked and not i_know_this_is_mocked:
        raise GateStatusError(
            "a mock backend env var is set but --i-know-this-is-mocked was not passed -- refusing to --apply "
            "against a mocked forge backend"
        )

    if action == "blocked":
        raise GateStatusBlocked(
            f"{reason}: refusing to create or update a gate-status comment -- needs human resolution"
        )

    target = {"repo": repo, "pr": pr} if forge == FORGE_GITHUB else {"project_path": project_path, "mr_iid": mr_iid}

    if action == "unchanged":
        lock_path = acquire_lock(root, task_id, forge, break_lock=break_lock)
        try:
            ledger = read_ledger(root, task_id, forge)
            ledger.update(
                schema_version=LEDGER_SCHEMA_VERSION, task_id=task_id, forge=forge, target=target,
                bot_username=verified_username, mocked=mocked, marker=marker,
            )
            ledger.setdefault("entries", [])
            ledger["entries"].append(
                {"action": "unchanged", "comment_id": matched["id"] if matched else None, "recorded_at": now()}
            )
            write_ledger(root, task_id, ledger, forge)
        finally:
            release_lock(lock_path)
        return {**summary, "comment_id": matched["id"] if matched else None}

    lock_path = acquire_lock(root, task_id, forge, break_lock=break_lock)
    try:
        ledger = read_ledger(root, task_id, forge)
        ledger.update(
            schema_version=LEDGER_SCHEMA_VERSION, task_id=task_id, forge=forge, target=target,
            bot_username=verified_username, mocked=mocked, marker=marker,
        )
        ledger.setdefault("entries", [])

        if action == "create":
            result_comment = adapter.create_comment(body)
        else:
            result_comment = adapter.update_comment(matched["id"], body)

        author_ok = (result_comment.get("author") or "").lower() == verified_username.lower()
        body_ok = result_comment.get("body") == body
        if not (author_ok and body_ok):
            ledger["entries"].append(
                {
                    "action": action, "status": "suspect", "comment_id": result_comment.get("id"),
                    "recorded_at": now(),
                    "detail": "post-write verification failed: author or body mismatch after create/update",
                }
            )
            write_ledger(root, task_id, ledger, forge)
            raise GateStatusBlocked(
                f"post-write verification failed for {action} on {forge} -- author or body did not match "
                "after the write; aborting immediately"
            )

        ledger["entries"].append(
            {"action": action, "status": "verified", "comment_id": result_comment.get("id"), "recorded_at": now()}
        )
        write_ledger(root, task_id, ledger, forge)
        return {**summary, "comment_id": result_comment.get("id")}
    finally:
        release_lock(lock_path)
