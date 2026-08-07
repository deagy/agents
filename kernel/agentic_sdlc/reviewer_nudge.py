"""`publish-reviewer-nudge` / `list-reviewer-nudge`: post (and idempotently
update in place on re-run) an advisory, GitHub-only comment on a task's PR
suggesting who a human might ask to review it, derived from
`gate_reviewers.py`'s existing classification.

## Why this exists instead of the blocked write-capable feature

`request-gate-reviewers` (`gate_reviewers.py`) is deliberately read-only:
actually requesting PR reviewers needs a GitHub token with
`Pull requests: write` scope, which has no narrower equivalent and also
permits editing/closing PRs and changing labels -- a real permission
escalation that has not been signed off (see that module's own docstring).
This command never requests that scope and never calls a reviewer-request
endpoint. It reuses `publish-gate-status`'s ALREADY-APPROVED, already-in-use
comment-write capability (`Issues: write` scope, via `github_status_write.py`)
to post a *suggestion* comment naming who a human might ask -- nothing here
notifies, assigns, or requests anything from anyone (see "No GitHub
mention/notification surface" below, and the mandatory advisory paragraph
this module always renders).

## Reuse, not reimplementation

Eligibility, self-approval/independence poisoning, and login-level
motivation aggregation are `gate_reviewers.build_plan()`'s logic, not
duplicated here. Getting the actual *classification* per login
(`already-requested` / `already-reviewed` / `review-stale` / `to-request` /
`withheld-conflict` / the two resolution-failure reasons) additionally
requires live GitHub state -- identity verification, the PR fetch/validation,
requested-reviewers, reviews, user-existence, and collaborator checks --
which only exists in `gate_reviewers.run()` (`build_plan()` alone returns
motivations/poisoning/refusals, not the final classification against live
GitHub state). This module therefore calls `gate_reviewers.run()` directly
rather than calling `build_plan()` a second time and reimplementing the rest
of `run()`'s GitHub-state plumbing beside it -- that would be a second,
divergence-prone call path for identity verification, PR fetch/validation,
and the requested-reviewers/reviews/user-exists/collaborator checks, all of
which `gate_reviewers.run()` already implements once. Calling `run()`
necessarily also exercises `build_plan()` internally, so this still satisfies
"reuse `build_plan()`'s logic, do not reimplement it" -- see
`test_reviewer_nudge.py`'s `ReuseTests` (a source-inspection test asserting
this module never redefines eligibility/self-approval/motivation-aggregation
logic of its own).

For comment create/update/list/verify-identity, this module reuses
`gate_status.py`'s already-reviewed machinery directly: `gate_status.
GithubForgeAdapter` (paginated `list_comments`, `create_comment`,
`update_comment`, `verify_identity`) and `gate_status.classify()` (the
create/update/unchanged/blocked decision). Nothing here reimplements
pagination, the page cap, or the classification decision table.

## Data minimization / who is named, and who is not

- `already-requested` / `already-reviewed`: omitted entirely -- nothing to
  nudge about.
- `to-request` / `review-stale`: the only logins named in the posted
  comment, each with the gate(s) that motivate it. This is the entire
  purpose of the feature.
- `withheld-conflict`: NEVER named in the posted comment -- only a count
  ("N additional reviewer(s) not shown due to a gate-independence conflict
  -- see the full report locally"). Naming a specific person as conflicted
  (self-approval / PR-author-conflict / actor-is-reviewer) in a public PR
  comment would be a data-exposure regression from how `gate_reviewers.py`'s
  own report already keeps that reasoning internal-report-only; the full
  reason remains available locally via `request-gate-reviewers`, never in
  the public comment.
- `github-user-unresolved` / `not-a-collaborator`: omitted entirely, same as
  `already-requested`/`already-reviewed` -- these are resolution failures,
  not people a human can usefully nudge from a PR comment.

Only closed-enum / bundled-contract data is ever rendered: a GitHub login
(already existence-checked via `github_write.check_github_user_exists` and
collaborator-checked, inside `gate_reviewers.run()`), a gate id (`G1`-`G10`),
a bundled contract's gate name (`contracts/lifecycle-gates.json`, same
source `gate_status.py` uses), an `authority_type` (`independent-verifier` /
`human-approver`, a closed schema enum), and a fixed classification label.
The free-text `authority_requirements[].role` / `.rationale` fields on the
run record (schema-`nonEmpty` strings, not closed enums) are deliberately
NEVER rendered here, mirroring `gate_status.py`'s zero-injection-surface
design (see that module's own docstring) rather than `gate_issues.py`'s
`sanitize_free_text`/`sanitize_title_text` machinery, which exists
specifically because that module DOES render project-supplied free text.
`authority_type` stands in as this render's coarser, closed-enum "role"
signal instead. See `test_reviewer_nudge.py`'s `ContentWhitelistTests`.

## No GitHub mention/notification surface

Logins are rendered as `` `login` `` (backtick code span), never as a raw
`@login` GitHub-flavored-markdown mention. This is deliberate and
load-bearing: an `@login` mention in a posted comment DOES trigger a GitHub
notification, which would directly contradict the mandatory advisory's claim
that nobody has been notified. See `test_reviewer_nudge.py`'s
`NoMentionSurfaceTests`.

## Mandatory advisory (distinct wording from `gate_status.py`'s)

This is a nudge, not an approval-status render, and it is not the same claim
`gate_status.py` makes -- `gate_status.py`'s advisory says "this is not
approval evidence"; this module's advisory says "this is not a review
request and nobody has been notified", which is a different, module-specific
claim that needed its own wording rather than reusing that paragraph
verbatim. See `_ADVISORY_PARAGRAPH` below and
`test_reviewer_nudge.py`'s `AdvisoryWordingTests`.

## Marker (own domain tag, disjoint from the other three families)

`compute_nudge_marker(task_id) = sha256("reviewer-nudge\\x00" + task_id)[:16]`
-- domain-separated from `gate_issues.py`'s `compute_gate_marker`/
`compute_approval_marker` and from `gate_status.py`'s
`compute_status_marker` (see `gate_issues.py`'s marker table, which this
module's marker is also listed in). Embedded as
`<!-- agentic-sdlc:reviewer-nudge:v1:<marker> -->`; matching is on the
`<marker>` token only, never the `v1` version segment, exactly like
`gate_status.py`'s `_MARKER_PATTERN_TEMPLATE`.

## Ledger (diagnostics only, forge-qualified, never trusted for existence)

`<root>/.agentic-sdlc/runs/<task_id>/reviewer-nudge-github.json` + `.lock` --
GitHub-only (no `--forge` flag; there is no GitLab equivalent of this
feature yet, since `report-gate-reviewers-gitlab` does not exist -- see this
module's own docstring intro), a distinct file family from
`gate_issues.py`'s `gate-issues-<forge>.json` and `gate_status.py`'s
`gate-status-<forge>.json`, so no collision. Reuses `_forge_ledger.py`'s
durable-write and lock primitives, same as both of those. Existence is
always determined by scanning the PR's live comments for the marker, never
by trusting this ledger.

## No run-record schema change

This module never opens `run-record.schema.json` for writing and never adds
a field to it; it only reads `gate_reviewers.run()`'s report. See
`test_reviewer_nudge.py`'s `OrthogonalityTests`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from . import CONTRACTS, OVERLAY, load_json, now
from . import _forge_ledger, gate_issues, gate_reviewers, gate_status, github_status_write

LEDGER_SCHEMA_VERSION = 1
FORGE = "github"

TEMPLATE_VERSION = 1

_MARKER_PATTERN_TEMPLATE = r"<!-- agentic-sdlc:reviewer-nudge:v\d+:{marker} -->"

TO_NUDGE_CLASSIFICATIONS = frozenset({"to-request", "review-stale"})
WITHHELD_CLASSIFICATION = "withheld-conflict"
# Everything else in gate_reviewers.CLASSIFICATIONS (already-requested,
# already-reviewed, github-user-unresolved, not-a-collaborator) is silently
# omitted from the rendered comment -- see module docstring's "Data
# minimization" section.

_CLASSIFICATION_LABELS = {
    "to-request": "not yet requested",
    "review-stale": "review is stale (PR has changed since their last review)",
}

_ADVISORY_PARAGRAPH = (
    "**This is a suggestion, not a review request.**\n"
    "`agentic-sdlc` has not requested a review from anyone, and these people have not been notified by this\n"
    "comment being posted -- logins above are written as plain code spans, never as GitHub `@`-mentions,\n"
    "specifically so that posting or updating this comment does not itself trigger a GitHub notification to\n"
    "anyone. If you want to formally request a review, do so yourself in GitHub's UI (or `@`-mention someone\n"
    "directly, which does notify them -- this comment deliberately does not). Reacting or replying to this\n"
    "comment does not request, notify, or approve anything either. `agentic-sdlc` never reads this comment,\n"
    "its reactions, or its replies back into gate state -- like `publish-gate-status`'s comment, this render\n"
    "is strictly one-way and is never approval evidence."
)


class ReviewerNudgeError(ValueError):
    """Structural/policy failure -- CLI maps this to exit code 1."""


class ReviewerNudgeBlocked(ValueError):
    """Needs human resolution (ambiguous match, foreign author, page-cap
    exceeded, lock held, post-write verification mismatch) -- CLI maps this
    to exit code 2. Mirrors `gate_status.GateStatusBlocked`'s role exactly;
    kept as a distinct type so this module's CLI handler and callers never
    need to know `gate_status`'s exception hierarchy, even though the
    underlying page-cap check happens inside a reused `gate_status.
    GithubForgeAdapter` (see `run()` below, which catches and re-raises)."""


# --------------------------------------------------------------------------
# Marker
# --------------------------------------------------------------------------


def compute_nudge_marker(task_id: str) -> str:
    return hashlib.sha256(f"reviewer-nudge\x00{task_id}".encode("utf-8")).hexdigest()[:16]


def _marker_pattern(marker: str) -> re.Pattern[str]:
    return re.compile(_MARKER_PATTERN_TEMPLATE.format(marker=re.escape(marker)))


# --------------------------------------------------------------------------
# Rendering (pure; only closed-enum / bundled-contract data ever enters this
# -- see module docstring's "Data minimization" section)
# --------------------------------------------------------------------------


def render_reviewer_nudge_body(
    *, task_id: str, report: dict[str, Any], lifecycle_contracts: dict[str, dict[str, Any]], rendered_at: str,
) -> str:
    marker = compute_nudge_marker(task_id)
    task_hash = gate_issues.task_hash(task_id)

    lines = [
        f"<!-- agentic-sdlc:reviewer-nudge:v{TEMPLATE_VERSION}:{marker} -->",
        "> Machine-generated by agentic-sdlc. Not a human-authored artifact. **Not a review request.**",
        "> No one has been asked or notified by this comment being posted.",
        "",
        f"**Lifecycle reviewer nudge — task `{task_hash}`**",
        f"PR: {report['repo']}#{report['pr']} · rendered {rendered_at}",
        "",
    ]

    reviewers = report.get("reviewers", [])
    nudge_entries = [item for item in reviewers if item.get("classification") in TO_NUDGE_CLASSIFICATIONS]
    withheld_count = sum(1 for item in reviewers if item.get("classification") == WITHHELD_CLASSIFICATION)

    if nudge_entries:
        lines.append("Suggested reviewers:")
        lines.append("")
        for item in nudge_entries:
            login = item.get("login")
            classification = item.get("classification")
            status_label = _CLASSIFICATION_LABELS.get(classification, classification)
            lines.append(f"- `{login}` — {status_label}")
            for motivation in item.get("motivations", []):
                gate_id = motivation.get("gate_id")
                contract = lifecycle_contracts.get(gate_id, {})
                gate_name = contract.get("name", gate_id)
                authority_type = motivation.get("authority_type") or "authority"
                lines.append(f"  - {gate_id} {gate_name} ({authority_type})")
        lines.append("")
    else:
        lines.append("No reviewers to nudge for this PR right now.")
        lines.append("")

    if withheld_count:
        plural = "" if withheld_count == 1 else "s"
        lines.append(
            f"{withheld_count} additional reviewer{plural} not shown due to a gate-independence conflict "
            "— see the full report locally."
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.extend(_ADVISORY_PARAGRAPH.split("\n"))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Sidecar ledger (diagnostics only, never trusted for existence) -- reuses
# _forge_ledger.py exactly like gate_status.py / gate_issues.py
# --------------------------------------------------------------------------


def _ledger_path(root: Path, task_id: str) -> Path:
    return _forge_ledger.ledger_path(Path(root), OVERLAY, task_id, f"reviewer-nudge-{FORGE}.json")


def _lock_path(root: Path, task_id: str) -> Path:
    return _forge_ledger.lock_path(Path(root), OVERLAY, task_id, f"reviewer-nudge-{FORGE}.lock")


def _empty_ledger(task_id: str) -> dict[str, Any]:
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "task_id": task_id,
        "forge": FORGE,
        "target": None,
        "bot_username": None,
        "mocked": False,
        "marker": None,
        "entries": [],
    }


def read_ledger(root: Path, task_id: str) -> dict[str, Any]:
    path = _ledger_path(Path(root), task_id)
    if not path.is_file():
        return _empty_ledger(task_id)
    return json.loads(path.read_text(encoding="utf-8"))


def write_ledger(root: Path, task_id: str, ledger: dict[str, Any]) -> None:
    path = _ledger_path(Path(root), task_id)
    _forge_ledger.write_ledger_file(path, ledger, tmp_prefix=".reviewer-nudge.")


def acquire_lock(root: Path, task_id: str, *, break_lock: bool) -> Path:
    path = _lock_path(Path(root), task_id)
    try:
        return _forge_ledger.acquire_lock_file(path, break_lock=break_lock)
    except _forge_ledger.LedgerLockHeld as exc:
        raise ReviewerNudgeBlocked(str(exc)) from None


def release_lock(path: Path) -> None:
    _forge_ledger.release_lock_file(path)


# --------------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------------


def run(
    *, root: Path, task_id: str, repo: str, pr: int, as_bot: str, gates: list[str] | None,
    allow_classification: str | None, apply: bool, break_lock: bool = False,
    i_know_this_is_mocked: bool = False,
) -> dict[str, Any]:
    root = Path(root)

    # gate_reviewers.run() raises gate_reviewers.GateReviewersError (a
    # ValueError subclass) on any structural failure -- including a
    # classification mismatch, closed/merged PR, or repo mismatch. Left to
    # propagate: main() maps any ValueError to exit code 1, the same
    # mapping gate_reviewers's own CLI handler relies on.
    report = gate_reviewers.run(
        root=root, task_id=task_id, repo=repo, pr=pr, as_bot=as_bot, gates=gates,
        allow_classification=allow_classification,
    )

    lifecycle_contracts = {item["id"]: item for item in load_json(CONTRACTS / "lifecycle-gates.json")["gates"]}
    rendered_at = now()
    marker = compute_nudge_marker(task_id)
    body = render_reviewer_nudge_body(
        task_id=task_id, report=report, lifecycle_contracts=lifecycle_contracts, rendered_at=rendered_at,
    )

    adapter = gate_status.GithubForgeAdapter(repo=repo, pr=pr)
    mocked = bool(os.environ.get(github_status_write.GITHUB_WRITE_MOCK_ENV_VAR))

    try:
        verified_username = adapter.verify_identity(as_bot)
    except ValueError as exc:
        raise ReviewerNudgeError(str(exc)) from exc

    try:
        comments = adapter.list_comments()  # may raise gate_status.GateStatusBlocked (page cap)
    except gate_status.GateStatusBlocked as exc:
        raise ReviewerNudgeBlocked(str(exc)) from exc

    pattern = _marker_pattern(marker)
    matches = [
        comment for comment in comments
        if not comment.get("is_system") and pattern.search(comment.get("body") or "")
    ]
    action, reason, matched = gate_status.classify(matches, verified_username, body)

    nudged_logins = sorted(
        {item["login"] for item in report.get("reviewers", []) if item.get("classification") in TO_NUDGE_CLASSIFICATIONS}
    )
    withheld_count = sum(
        1 for item in report.get("reviewers", []) if item.get("classification") == WITHHELD_CLASSIFICATION
    )

    summary = {
        "mode": "apply" if apply else "dry-run",
        "task_id": task_id,
        "task_hash": gate_issues.task_hash(task_id),
        "repo": repo,
        "pr": pr,
        "marker": marker,
        "action": action,
        "reason": reason,
        "matched_comment_id": matched.get("id") if matched else None,
        "mocked": mocked,
        "body": body,
        "nudged_logins": nudged_logins,
        "withheld_count": withheld_count,
    }

    if not apply:
        # Dry-run never writes and never raises for an ambiguous/blocked
        # classification -- it only reports what an --apply run would do.
        return summary

    if mocked and not i_know_this_is_mocked:
        raise ReviewerNudgeError(
            "a mock backend env var is set but --i-know-this-is-mocked was not passed -- refusing to --apply "
            "against a mocked forge backend"
        )

    if action == "blocked":
        raise ReviewerNudgeBlocked(
            f"{reason}: refusing to create or update a reviewer-nudge comment -- needs human resolution"
        )

    target = {"repo": repo, "pr": pr}

    if action == "unchanged":
        lock_path = acquire_lock(root, task_id, break_lock=break_lock)
        try:
            ledger = read_ledger(root, task_id)
            ledger.update(
                schema_version=LEDGER_SCHEMA_VERSION, task_id=task_id, forge=FORGE, target=target,
                bot_username=verified_username, mocked=mocked, marker=marker,
            )
            ledger.setdefault("entries", [])
            ledger["entries"].append(
                {"action": "unchanged", "comment_id": matched["id"] if matched else None, "recorded_at": now()}
            )
            write_ledger(root, task_id, ledger)
        finally:
            release_lock(lock_path)
        return {**summary, "comment_id": matched["id"] if matched else None}

    lock_path = acquire_lock(root, task_id, break_lock=break_lock)
    try:
        ledger = read_ledger(root, task_id)
        ledger.update(
            schema_version=LEDGER_SCHEMA_VERSION, task_id=task_id, forge=FORGE, target=target,
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
            write_ledger(root, task_id, ledger)
            raise ReviewerNudgeBlocked(
                f"post-write verification failed for {action} -- author or body did not match after the "
                "write; aborting immediately"
            )

        ledger["entries"].append(
            {"action": action, "status": "verified", "comment_id": result_comment.get("id"), "recorded_at": now()}
        )
        write_ledger(root, task_id, ledger)
        return {**summary, "comment_id": result_comment.get("id")}
    finally:
        release_lock(lock_path)
