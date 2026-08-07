"""GitHub-review-as-resume adapter: turn a GitHub PR review into the same
`Approval` shape the graph's `human_approval_{gate_id}` interrupt expects
as its `Command(resume=...)` payload, so a human's real GitHub PR review
can stand in for a manually-typed approval decision.

Ported close to unchanged from `agentic_sdlc.py` (no project-overlay
dependency at all):

- `GITHUB_REVIEW_URI` / `parse_github_review_uri` (~64-66 / ~265-269)
- `normalize_commit_sha` (~272-276)
- `fetch_github_pr_reviews` (~279-299), including the exact
  `AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE` env-var mocking convention the
  legacy test suite uses, so tests here can run with zero network/`gh`
  dependency.
- `select_github_review` (~302-327) -- "latest review wins" semantics
  intact: reviews from `reviewer_login` (case-insensitive), with a valid
  `submitted_at`, optionally filtered to `commit_sha`, sorted by
  `submitted_at`; the single latest one must be an effective `APPROVED`
  (not dismissed), so a later `CHANGES_REQUESTED` after an earlier
  `APPROVED` from the same reviewer/commit correctly invalidates the
  approval.

Adapted, not ported unchanged:

- `record_github_approval` (~383-460ish) depended on two overlay-shaped
  concepts this package doesn't build: a project `authorities.json`
  (assigned human -> GitHub login bindings) and a live run-record JSON
  file read/written directly from disk. Neither belongs here yet (project
  overlays are later-phase scope, same as `validate.py`'s
  `gate_contracts`-dependent checks were made optional rather than
  force-built). `github_review_to_approval` below keeps the one piece of
  that function that *isn't* overlay-shaped -- "does this review's author
  match who you claim approved it" -- as an opt-in `expected_login` check,
  and drops the authorities.json/run-record-file plumbing entirely.

`resume_gate_with_github_approval` is the integration point proving this
is real plumbing: it resumes a compiled graph's `human_approval_{gate_id}`
interrupt with an `Approval` built by `github_review_to_approval`, via the
exact same `graph.invoke(Command(resume=approval), config=config)`
mechanism `graph.py` already expects (see `graph.py`'s `human_approval`
closure, which reads `decision.get("status")`, `decision.get("approver")`,
and `decision.get("evidence_refs")` off the resume value -- `decided_at`
is not read from the resume payload at all; the node always recomputes it
itself via its own `_now()`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provider import fingerprint
from .state import Approval

GITHUB_REVIEW_URI = re.compile(
    r"^github-review:(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+):"
    r"pull/(?P<pull>[0-9]+):review/(?P<review>[0-9]+):reviewer/(?P<login>[A-Za-z0-9-]+)$"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_valid_datetime(value: Any) -> bool:
    """Port of the legacy `is_valid_datetime` (agentic_sdlc.py ~74-81) /
    `validate.py`'s `_is_valid_datetime` -- duplicated here (rather than
    imported from `validate.py`) so this module has no dependency on the
    validation module; both are small, independent ports of the same
    legacy predicate.
    """
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def parse_github_review_uri(value: str) -> dict[str, str] | None:
    """Port of `agentic_sdlc.py`'s `parse_github_review_uri` (~265-269)."""
    match = GITHUB_REVIEW_URI.fullmatch(value)
    if not match:
        return None
    return match.groupdict()


def normalize_commit_sha(value: Any) -> str | None:
    """Port of `agentic_sdlc.py`'s `normalize_commit_sha` (~272-276)."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def fetch_github_pr_reviews(repo: str, pr: int) -> list[dict[str, Any]]:
    """Port of `agentic_sdlc.py`'s `fetch_github_pr_reviews` (~279-299).

    When `AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE` is set, reads a JSON
    array from that file instead of shelling out to `gh api` -- the exact
    mocking convention the legacy test suite uses, ported verbatim so
    tests here need neither network access nor a `gh` binary.
    """
    mock_path = os.environ.get("AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE")
    if mock_path:
        payload = json.loads(Path(mock_path).read_text(encoding="utf-8"))
    else:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/pulls/{pr}/reviews"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown gh api failure"
            raise ValueError(f"unable to fetch GitHub reviews for {repo} PR {pr}: {detail}")
        payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise ValueError("GitHub reviews response must be a JSON array")
    reviews = [item for item in payload if isinstance(item, dict)]
    if len(reviews) != len(payload):
        raise ValueError("GitHub reviews response contains non-object entries")
    return reviews


def select_github_review(
    reviews: list[dict[str, Any]], reviewer_login: str, commit_sha: str | None = None
) -> dict[str, Any]:
    """Port of `agentic_sdlc.py`'s `select_github_review` (~302-327).

    Filters `reviews` to those from `reviewer_login` (case-insensitive)
    with a valid `submitted_at` timestamp and (if `commit_sha` is given) a
    matching `commit_id`; sorts the surviving reviews by `submitted_at`
    and takes the latest. That latest review must be an effective
    `APPROVED` (state == "APPROVED" and not dismissed) or this raises --
    "latest review wins", so a later `CHANGES_REQUESTED` from the same
    reviewer/commit correctly invalidates an earlier `APPROVED`.
    """
    normalized_login = reviewer_login.lower()
    normalized_commit = normalize_commit_sha(commit_sha)
    matching: list[dict[str, Any]] = []
    for review in reviews:
        user = review.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        submitted_at = review.get("submitted_at")
        review_commit = normalize_commit_sha(review.get("commit_id"))
        if not isinstance(login, str) or login.lower() != normalized_login:
            continue
        if not _is_valid_datetime(submitted_at):
            continue
        if normalized_commit and review_commit != normalized_commit:
            continue
        matching.append(review)
    if not matching:
        commit_text = f" at commit {commit_sha}" if commit_sha else ""
        raise ValueError(f"no GitHub review found for reviewer {reviewer_login}{commit_text}")
    matching.sort(key=lambda review: str(review.get("submitted_at")))
    latest = matching[-1]
    if latest.get("state") != "APPROVED" or latest.get("dismissed_state") in {"DISMISSED", "dismissed"}:
        raise ValueError(f"latest GitHub review for reviewer {reviewer_login} is not an effective approval")
    return latest


def github_review_to_approval(
    review: dict[str, Any],
    *,
    gate_id: str,
    authority_id: str,
    role_label: str,
    repo: str,
    pr: int,
    expected_login: str | None = None,
    decided_at: str | None = None,
) -> Approval:
    """Adapted from `agentic_sdlc.py`'s `record_github_approval`
    (~383-460ish): builds the same `Approval`-shaped record (status
    "approved", `approver` Identity, `decided_at`, one `evidence_refs`
    entry carrying a `github-review:...` URI and a sha256 evidence hash)
    from an *already-selected* review (the output of
    `select_github_review`), given just enough context to build the URI
    and evidence payload.

    Unlike the legacy function, this does **not** read or write a project
    `authorities.json` / run-record JSON file -- neither concept exists in
    this package yet (see module docstring). The one piece of the legacy
    cross-check that survives is `expected_login`: if supplied, the
    review's reviewer login must match it case-insensitively or this
    raises `ValueError`; if omitted, that check is skipped entirely
    (mirrors how `validate.py`'s `gate_contracts`-dependent checks are
    optional rather than force-building the overlay concept they'd
    otherwise depend on).

    `authority_id` becomes the `Approval.approver.id` (the legacy
    function used the authority's *assigned human* id looked up from
    `authorities.json`; without that overlay, the caller-supplied
    authority id itself is the best available stand-in identity here).
    """
    user = review.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(login, str) or not login:
        raise ValueError("review is missing a reviewer login")
    if expected_login is not None and login.lower() != expected_login.lower():
        raise ValueError(
            f"GitHub reviewer {login} does not match expected authority login {expected_login}"
        )

    review_id = review.get("id")
    if review_id is None:
        raise ValueError("review is missing an id")

    submitted_at = review.get("submitted_at")
    if not _is_valid_datetime(submitted_at):
        raise ValueError(f"review submitted_at {submitted_at!r} is not a valid date-time")

    commit_sha = normalize_commit_sha(review.get("commit_id"))
    normalized_login = login.lower()
    review_uri = f"github-review:{repo}:pull/{pr}:review/{review_id}:reviewer/{normalized_login}"
    if parse_github_review_uri(review_uri) is None:
        raise ValueError(f"invalid GitHub review URI components for {review_uri}")

    chosen_time = decided_at or _now()

    evidence_payload = {
        "gate_id": gate_id,
        "authority_id": authority_id,
        "repo": repo,
        "pull": pr,
        "review_id": review_id,
        "reviewer_login": login,
        "decided_at": chosen_time,
        "commit_sha": commit_sha,
    }
    evidence_hash = fingerprint(evidence_payload).removeprefix("sha256:")

    return Approval(
        status="approved",
        approver={"id": authority_id, "role": role_label, "kind": "human"},
        decided_at=chosen_time,
        evidence_refs=[
            {
                "evidence_id": f"{gate_id.lower()}-{authority_id}-github-review-{review_id}",
                "uri": review_uri,
                "hash_algorithm": "sha256",
                "hash": evidence_hash,
                "classification": "internal",
            }
        ],
    )


def resume_gate_with_github_approval(
    graph: Any, config: dict[str, Any], approval: Approval
) -> dict[str, Any]:
    """Resume a compiled graph suspended at a `human_approval_{gate_id}`
    interrupt with an `Approval` built by `github_review_to_approval`.

    Thin wrapper around the exact `interrupt()`/`Command(resume=...)`
    mechanism `graph.py` already implements: `graph.py`'s
    `human_approval_{gate_id}` node reads `decision.get("status")`,
    `decision.get("approver")`, and `decision.get("evidence_refs")` off
    whatever value is passed to `Command(resume=...)` (see `graph.py`'s
    `human_approval` closure). `github_review_to_approval`'s return value
    is a plain dict with exactly those keys (plus `decided_at`, which the
    node does not read from the resume payload at all -- it always
    recomputes its own via `_now()` -- so its presence here is harmless).

    This function adds no behavior beyond that single `graph.invoke`
    call; it exists so callers have one obvious place to resume a gate
    with a GitHub-review-derived approval, matching the shape of the
    other graph-driving helpers in `reentry.py`.
    """
    from langgraph.types import Command

    return graph.invoke(Command(resume=approval), config=config)
