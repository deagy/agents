"""`request-gate-reviewers-gitlab`: report which GitLab usernames would be
set as MR reviewers for a task's lifecycle gates (derived from
`authority_requirements[]` + `authorities.json`), and which are already set
as reviewers or have already approved.

## GitLab sibling of `request-gate-reviewers`, not a `--forge` flag on it

`gate_reviewers.py`'s CLI has no `--forge` flag today (it is GitHub-only).
`publish-gate-status` (`gate_status.py`) *does* have `--forge {github,gitlab}`
because its per-forge adapters (`GithubForgeAdapter`/`GitlabForgeAdapter`)
share an identical `create`/`update`/`unchanged`/`blocked` result shape and
an identical comment-marker protocol -- the forges are genuinely
interchangeable from that command's point of view. This feature is not:
GitHub's classification vocabulary (`already-requested`, `already-reviewed`,
`review-stale`, `to-request`) and GitLab's (`already-reviewer`,
`already-approved`, `to-request` -- no `review-stale` equivalent, see below)
are structurally different, and GitLab adds a resolution-ambiguity case
(`gitlab-user-ambiguous`) that has no GitHub counterpart at all (GitHub's
`GET /users/{login}` is an exact lookup; GitLab's `GET /users?username=` is a
search). Folding both behind one `--forge` flag would mean a single result
schema pretending to support classifications the other forge cannot produce,
or a run of `if forge == "gitlab": ...` branches sprinkled through what is
otherwise a straight-line report -- worse than two small, forge-named
modules. What *is* shared, because it is genuinely forge-agnostic policy and
not forge-specific mechanics, is imported directly from `gate_reviewers.py`
rather than duplicated: `check_gate_eligibility`, `_default_gate_ids`,
`is_gate_self_approval`, and the generalized `build_plan` (parameterized by
`resolve_login`/`no_binding_reason`/`author_conflict_reason` precisely so
this module can call it without copying its independence/poisoning logic --
see `build_plan`'s own docstring in `gate_reviewers.py`).

## Read-only / reporting-only in this version -- there is no write path

Exactly the same posture as `gate_reviewers.py`: no `--apply` flag, no code
path that sets `reviewer_ids`. Setting MR reviewers requires a GitLab token
with API write scope; introducing that write capability is a real
permission-escalation decision needing explicit human sign-off, not
something to infer from this feature's name. `gitlab_write.py`'s new
`fetch_gitlab_mr` (used here) is a GET call only -- see its own docstring.

## No ledger, and no `list-gate-reviewer-requests-gitlab` companion command

Same reasoning as `gate_reviewers.py`'s module docstring: this command
performs no action, only a live report, so a fresh invocation is always at
least as trustworthy as any ledger could be (GitLab MR reviewer/approval
state can change between runs).

## Eligibility, self-approval/independence, and login-level "poisoning"

Identical policy to `gate_reviewers.py` -- reused directly via
`check_gate_eligibility`/`_default_gate_ids`/`is_gate_self_approval`/
`build_plan` (imported, not duplicated; see the module-docstring section
above). An MR reviewer assignment is MR-wide, not gate-scoped, exactly like
a GitHub PR review request, so the same poisoning rule applies: if any
in-scope `(gate, authority)` pair refuses a resolved username for one of the
three independence reasons (`self-approval`, `mr-author-conflict`,
`actor-is-reviewer`), that username is withheld from ALL of its motivations.

## GitLab-specific resolution: `gitlab-user-unresolved` / `gitlab-user-ambiguous`

`GET /users/{login}` (GitHub, exact match) has no GitLab analog. GitLab's
`GET /users?username=` (`gitlab_write.resolve_gitlab_user_id`, already used
by `gate_issues.py` for the same reason) is search-based and can return zero,
one, or multiple active matches. This module reuses that existing function
rather than reimplementing username resolution, and reuses `gate_issues.py`'s
established "count of *active*-state matches" rule (0 -> unresolved, >1 ->
ambiguous) as a small local copy (`_resolve_active_usernames`) rather than
importing `gate_issues.py`'s private helper -- following the precedent
`gate_reviewers.py`'s own docstring sets for *this specific kind* of small,
forge/feature-specific helper (its "Eligibility"/"Self-approval" sections
explain why a local copy was chosen over a cross-feature import there; the
same reasoning applies to a resolution-classification helper here).

## No GitLab equivalent of `not-a-collaborator`

`gate_reviewers.py` reports `not-a-collaborator` when a resolved GitHub login
is not a repository collaborator (`GET /repos/{repo}/collaborators/{login}`).
This module deliberately has no equivalent reason code: the requested reason
codes for this feature (spec) do not include a project-membership check, and
`glab api` has no single low-cost "is this user a member of this project"
endpoint the way GitHub's collaborators endpoint is -- GitLab's nearest
equivalent (`GET /projects/:id/members/all/:user_id`) is a per-user lookup
keyed by the *numeric* user id already resolved via `resolve_gitlab_user_id`,
which would add another round-trip and another problem classification not
asked for here. `test_gate_reviewers_gitlab.py` asserts this reason code is
absent as a regression guard, mirroring `gate_reviewers.py`'s own
`github-user-ambiguous`-absence test in the other direction.

## No `review-stale` classification -- a genuine, verified API gap, not a design choice

GitHub's per-review `commit_id` (`gate_reviewers.classify_login`) lets a
review be matched against the PR's exact head SHA, so a review submitted
against an older commit is distinguishable from one submitted at HEAD.
GitLab's merge-request-level approvals endpoint
(`GET .../merge_requests/:iid/approvals`, wrapped by
`agentic_sdlc.fetch_gitlab_mr_approvals` /
`gitlab_approval_records_from_api_response`) has **no per-approver commit
field**. Its one `sha` field is the *MR's* current diff-head SHA, applied
uniformly to every entry in `approved_by` -- see that function's own,
extensively commented normalization logic (`agentic_sdlc/__init__.py`,
`gitlab_approval_records_from_api_response`), which already documents this
exact limitation for `approve-from-gitlab-mr`'s `--commit-sha` filtering:
whether a given approval is genuinely "for the current head" depends on the
GitLab project having "reset approvals on push" enabled, a precondition
neither that adapter nor this one can observe or verify from the API
response alone. Faking a `review-stale` classification by comparing the
MR-level `sha` to the MR's current head would misrepresent *every* approver
identically (either all "stale" or all "fresh" together, never
per-approver) -- worse than no classification, because it would look
per-approver-precise without being so. This module therefore has exactly one
"has approved" classification, `already-approved`, with no staleness
qualifier, and this gap is intentional and permanent unless GitLab's API
adds per-approval commit data. `mr_head_sha` is still surfaced in this
module's report output (for the same "documentation, not classification
input" reason `pr_head_sha` is surfaced by the GitHub version) purely so a
human reader can manually cross-check currency if they choose to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import (
    CONTRACTS,
    OVERLAY,
    authority_gitlab_username,
    confined_path,
    fetch_gitlab_mr_approvals,
    load_json,
)
from . import gate_reviewers, gitlab_write

PROBLEM_CLASSIFICATIONS = frozenset({"withheld-conflict", "gitlab-user-unresolved", "gitlab-user-ambiguous"})
CLASSIFICATIONS = frozenset({"already-reviewer", "already-approved", "to-request"} | PROBLEM_CLASSIFICATIONS)

# Re-exported so callers/tests can use this module's own name for the shared
# forge-agnostic eligibility/independence policy without reaching into
# gate_reviewers.py directly.
check_gate_eligibility = gate_reviewers.check_gate_eligibility
_default_gate_ids = gate_reviewers._default_gate_ids
is_gate_self_approval = gate_reviewers.is_gate_self_approval


class GateReviewersGitlabError(ValueError):
    """Structural/policy failure -- CLI maps this to exit code 1. Mirrors
    `gate_reviewers.GateReviewersError`'s scope exactly (missing run record,
    MR not found/closed/merged/project-path-mismatch, an `--as-bot` identity
    mismatch, malformed forge responses, an explicitly-requested gate that
    fails eligibility) -- kept as a module-local class, not a re-export of
    the GitHub version's exception, so callers can distinguish which forge's
    report failed without inspecting the message text."""


# --------------------------------------------------------------------------
# GitLab username resolution (mirrors gate_issues.py's active-match rule;
# see module docstring for why this is a local copy)
# --------------------------------------------------------------------------


def _resolve_active_usernames(username: str) -> list[dict[str, Any]]:
    matches = gitlab_write.resolve_gitlab_user_id(username)
    return [
        entry
        for entry in matches
        if isinstance(entry, dict) and isinstance(entry.get("id"), int) and entry.get("state", "active") == "active"
    ]


# --------------------------------------------------------------------------
# Existence / review classification
# --------------------------------------------------------------------------


def classify_username(*, username: str, reviewer_usernames: set[str], approved_usernames: set[str]) -> str:
    """Priority: already-approved > already-reviewer > to-request. There is
    no `review-stale` case here -- see the module docstring's "No
    `review-stale` classification" section for why that is a genuine,
    verified GitLab API gap rather than an oversight."""
    normalized = username.lower()
    if normalized in approved_usernames:
        return "already-approved"
    if normalized in reviewer_usernames:
        return "already-reviewer"
    return "to-request"


# --------------------------------------------------------------------------
# MR field extraction
# --------------------------------------------------------------------------


def _mr_project_path(mr_raw: dict[str, Any]) -> str | None:
    references = mr_raw.get("references")
    if isinstance(references, dict):
        full_ref = references.get("full")
        if isinstance(full_ref, str) and "!" in full_ref:
            return full_ref.rsplit("!", 1)[0]
    return None


def _mr_is_draft(mr_raw: dict[str, Any]) -> bool:
    """Prefers the top-level `draft` boolean (present on current GitLab
    versions); falls back to the legacy `Draft:`/`WIP:` title-prefix
    convention (`work_in_progress` predates the `draft` field and some
    self-hosted instances may still only expose the title convention)."""
    draft_field = mr_raw.get("draft")
    if isinstance(draft_field, bool):
        return draft_field
    work_in_progress = mr_raw.get("work_in_progress")
    if isinstance(work_in_progress, bool):
        return work_in_progress
    title = mr_raw.get("title")
    if isinstance(title, str):
        normalized = title.strip().lower()
        return normalized.startswith("draft:") or normalized.startswith("wip:")
    return False


# --------------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------------


def run(
    *, root: Path, task_id: str, project_path: str, mr_iid: int, as_bot: str, gates: list[str] | None,
    allow_classification: str | None,
) -> dict[str, Any]:
    root = Path(root)
    overlay_dir = confined_path(root, OVERLAY)
    record_path = confined_path(root, OVERLAY, "runs", task_id, "run-record.json")
    dispatch_path = confined_path(root, OVERLAY, "runs", task_id, "dispatch-plan.json")
    record = load_json(record_path)
    dispatch_plan = load_json(dispatch_path)
    authorities = load_json(overlay_dir / "authorities.json")
    # lifecycle_contracts is loaded for parity with gate_reviewers.run() and
    # to fail closed on a corrupted bundled contract, even though this
    # report does not currently render gate name/phase text anywhere.
    load_json(CONTRACTS / "lifecycle-gates.json")
    gate_by_id = {item["gate_id"]: item for item in record.get("lifecycle_gates", [])}

    if allow_classification is None or allow_classification != record.get("classification"):
        raise GateReviewersGitlabError(
            "--allow-classification must be supplied and exactly match the task's classification "
            f"(got {allow_classification!r}, task classification is {record.get('classification')!r})"
        )

    try:
        if gates:
            gate_ids = []
            for gate_id in gates:
                check_gate_eligibility(gate_id, dispatch_plan, gate_by_id.get(gate_id))
                gate_ids.append(gate_id)
        else:
            gate_ids = _default_gate_ids(dispatch_plan, gate_by_id)
    except gate_reviewers.GateReviewersError as exc:
        raise GateReviewersGitlabError(str(exc)) from exc

    try:
        verified_username = gitlab_write.verify_gitlab_identity(as_bot)
    except ValueError as exc:
        raise GateReviewersGitlabError(str(exc)) from exc

    try:
        mr_raw = gitlab_write.fetch_gitlab_mr(project_path, mr_iid)
    except (gitlab_write.MRNotFound, ValueError) as exc:
        raise GateReviewersGitlabError(str(exc)) from exc
    if not isinstance(mr_raw, dict):
        raise GateReviewersGitlabError(f"malformed MR response for {project_path}!{mr_iid}")

    state = mr_raw.get("state")
    if state in {"closed", "merged"}:
        raise GateReviewersGitlabError(f"GitLab MR {project_path}!{mr_iid} is closed or merged (state={state!r})")

    mr_project_path = _mr_project_path(mr_raw)
    if mr_project_path is None or mr_project_path.lower() != project_path.lower():
        raise GateReviewersGitlabError(
            f"GitLab MR {project_path}!{mr_iid}'s project ({mr_project_path!r}) does not match "
            f"--project-path {project_path!r}"
        )

    head_sha = mr_raw.get("sha")
    if not isinstance(head_sha, str) or not head_sha:
        raise GateReviewersGitlabError(f"GitLab MR {project_path}!{mr_iid} response is missing sha")

    draft = _mr_is_draft(mr_raw)
    mr_author = mr_raw.get("author") if isinstance(mr_raw.get("author"), dict) else {}
    mr_author_username = mr_author.get("username") if isinstance(mr_author.get("username"), str) else None

    motivations_by_login, login_display, poisoned_by_login, skipped, refusals = gate_reviewers.build_plan(
        gate_ids=gate_ids, record=record, authorities=authorities,
        pr_author_login=mr_author_username, as_bot_login=verified_username,
        resolve_login=authority_gitlab_username,
        no_binding_reason="no-gitlab-binding",
        author_conflict_reason="mr-author-conflict",
    )

    reviewers_field = mr_raw.get("reviewers")
    reviewer_usernames: set[str] = set()
    if isinstance(reviewers_field, list):
        for entry in reviewers_field:
            username = entry.get("username") if isinstance(entry, dict) else None
            if isinstance(username, str) and username:
                reviewer_usernames.add(username.lower())

    try:
        approvals = fetch_gitlab_mr_approvals(project_path, mr_iid)
    except ValueError as exc:
        raise GateReviewersGitlabError(str(exc)) from exc
    approved_usernames = {
        approval["username"].lower()
        for approval in approvals
        if isinstance(approval.get("username"), str)
    }

    reviewers_report: list[dict[str, Any]] = []
    for key, motivations in motivations_by_login.items():
        display_username = login_display[key]
        motivation_dicts = [m.as_dict() for m in motivations]

        if key in poisoned_by_login:
            reviewers_report.append({
                "username": display_username,
                "classification": "withheld-conflict",
                "motivations": motivation_dicts,
                "withheld_cause": poisoned_by_login[key].as_dict(),
            })
            continue

        try:
            active_matches = _resolve_active_usernames(display_username)
        except ValueError as exc:
            raise GateReviewersGitlabError(str(exc)) from exc
        if len(active_matches) == 0:
            reviewers_report.append({
                "username": display_username, "classification": "gitlab-user-unresolved",
                "motivations": motivation_dicts, "withheld_cause": None,
            })
            continue
        if len(active_matches) > 1:
            reviewers_report.append({
                "username": display_username, "classification": "gitlab-user-ambiguous",
                "motivations": motivation_dicts, "withheld_cause": None,
            })
            continue

        classification = classify_username(
            username=display_username, reviewer_usernames=reviewer_usernames, approved_usernames=approved_usernames,
        )
        reviewers_report.append({
            "username": display_username, "classification": classification,
            "motivations": motivation_dicts, "withheld_cause": None,
        })

    reviewers_report.sort(key=lambda item: item["username"].lower())

    summary: dict[str, int] = {}
    for item in reviewers_report:
        summary[item["classification"]] = summary.get(item["classification"], 0) + 1

    return {
        "project_path": project_path,
        "mr_iid": mr_iid,
        "mr_head_sha": head_sha,
        "mr_draft": draft,
        "mr_author_username": mr_author_username,
        "as_bot_username": verified_username,
        "gate_ids": gate_ids,
        "reviewers": reviewers_report,
        "skipped": [entry.as_dict() for entry in skipped],
        "refusals": [entry.as_dict() for entry in refusals],
        "summary": summary,
    }
