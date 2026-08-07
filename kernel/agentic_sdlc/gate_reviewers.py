"""`request-gate-reviewers`: report which GitHub logins would be requested
as PR reviewers for a task's lifecycle gates (derived from
`authority_requirements[]` + `authorities.json`), and which are already
requested or have already reviewed.

## Read-only / reporting-only in this version -- there is no write path

**This version never calls a write endpoint. There is no `--apply` flag and
no code path that posts a review request.** Requesting PR reviewers
requires a GitHub token with `Pull requests: write` scope, which has no
narrower equivalent and also permits editing/closing PRs and changing
labels -- introducing that write capability is a real permission-escalation
decision that needs explicit human sign-off before it is built, not
something to infer from this feature's name. This read-only version needs
no new GitHub permissions beyond what the kernel already has (read-only
PR/reviews access, via `fetch_github_pr_reviews` in `agentic_sdlc/__init__.py`).
`github_write.py` (despite its historical-pattern name, mirroring
`gitlab_write.py`) implements GET calls only; see its own module docstring.

## No ledger, and no `list-gate-reviewer-requests` companion command

`create-gate-issues`/`list-gate-issues` (`gate_issues.py`) pairs a live
action with a diagnostics-only sidecar ledger because *something happens*
that is useful to remember between runs (an issue was created or reused).
This command performs no action at all -- it is a live report, and a fresh
invocation is always at least as accurate as anything a ledger could cache
(GitHub review/requested-reviewer state can change between runs; a stale
ledger would only ever be *less* trustworthy than re-querying). Persisting
"here is what the report said last time" would provide no additional
Value over just re-running the (cheap, read-only) report, so no ledger file
is written and there is no `list-gate-reviewer-requests` command. If a
future write path is added, revisit this: an *applied* review-request
action would have the same "did this already happen" idempotency need
`gate_issues.py` has, and would likely want its own ledger at that point.

## Eligibility

Mirrors `gate_issues.check_gate_eligibility`'s rules exactly (gate in the
dispatch plan's configured set, `applicability == "applicable"`,
`status != "invalidated"`, no pending `required_reentry_gate`) but is
implemented as a local, self-contained copy rather than calling into
`gate_issues.py` directly: that module's `GateIssuesError`/`GateIssuesBlocked`
exception pair encodes a dry-run/apply distinction this command does not
have (see above), so importing it would require translating between two
non-corresponding exception hierarchies for no benefit. A future
consolidation could extract a shared, exception-generic eligibility checker
that both modules call into.

## Self-approval / independence

`is_gate_self_approval` (comparison semantics: assignee identity against
every `gate["preparers"][].id` and `gate["independent_verifier"].id` on the
run record) now lives in `agentic_sdlc/__init__.py`, shared with
`gate_issues.py` -- both modules import the same implementation rather than
maintaining duplicate copies.

## Login-level "poisoning"

A GitHub review request is PR-wide, not gate-scoped. If any in-scope
`(gate, authority)` pair refuses a given resolved login for one of the three
*independence* reasons (`self-approval`, `pr-author-conflict`,
`actor-is-reviewer`), that login is withheld from ALL of its motivations for
this report, even ones that would otherwise be clean -- inviting that login
to review the PR at all would also satisfy the conflicting gate, since
GitHub review requests aren't scoped to a subset of a PR's changes.
Resolution failures (`no-github-binding`, `github-user-unresolved`,
`not-a-collaborator`) are per-pair or per-login properties, not independence
conflicts, and do not poison other motivations for the same login.

## No `github-user-ambiguous` reason code

`GET /users/{login}` (`github_write.check_github_user_exists`) is an exact
lookup (404, or exactly one match) -- unlike GitLab's search-based
`GET /users?username=` (which `gate_issues.py`'s `gitlab-user-ambiguous`
reason code exists to handle). Do not port that GitLab-specific reason code
across; `test_gate_reviewers.py` asserts it is absent as a regression guard.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import (
    CONTRACTS,
    GATE_IDS,
    OVERLAY,
    authority_github_login,
    confined_path,
    fetch_github_pr_reviews,
    is_gate_self_approval,
    load_json,
    normalize_commit_sha,
)
from . import github_write

INDEPENDENCE_REASONS = frozenset({"self-approval", "pr-author-conflict", "actor-is-reviewer"})
PROBLEM_CLASSIFICATIONS = frozenset({"withheld-conflict", "github-user-unresolved", "not-a-collaborator"})
CLASSIFICATIONS = frozenset(
    {"already-requested", "already-reviewed", "review-stale", "to-request"} | PROBLEM_CLASSIFICATIONS
)


class GateReviewersError(ValueError):
    """Structural/policy failure -- CLI maps this to exit code 1. Covers a
    missing run record, PR not found/closed/merged/repo-mismatch, an
    `--as-bot` identity mismatch, malformed forge responses, and (this
    module's own scoping decision) an explicitly-requested gate that fails
    eligibility -- there is no dry-run/apply split here for a separate
    "blocked, needs human resolution but the run otherwise continues"
    category the way `gate_issues.GateIssuesBlocked` has, so any
    precondition failure that prevents building the report at all is
    treated as structural."""


# --------------------------------------------------------------------------
# Eligibility (mirrors gate_issues.check_gate_eligibility; see module
# docstring for why this is a local copy, not a shared import)
# --------------------------------------------------------------------------


def _configured_gate_ids(dispatch_plan: dict[str, Any]) -> set[str]:
    return {
        item.get("gate_id")
        for item in dispatch_plan.get("gate_dispatch", [])
        if item.get("status") == "required"
    }


def check_gate_eligibility(gate_id: str, dispatch_plan: dict[str, Any], gate_record: dict[str, Any] | None) -> None:
    if gate_id not in GATE_IDS:
        raise GateReviewersError(f"unknown gate id: {gate_id!r}")
    if gate_record is None:
        raise GateReviewersError(
            f"gate {gate_id} not found in the run record's lifecycle_gates array "
            "(lookup is by gate_id, not index; the array must contain exactly G1-G10)"
        )
    if gate_id not in _configured_gate_ids(dispatch_plan):
        raise GateReviewersError(f"gate {gate_id} is not part of the task's configured (dispatch-plan) gate set")
    if gate_record.get("applicability") != "applicable":
        raise GateReviewersError(
            f"gate {gate_id} applicability is {gate_record.get('applicability')!r}, not 'applicable'"
        )
    if gate_record.get("status") == "invalidated":
        raise GateReviewersError(f"gate {gate_id} status is 'invalidated'")
    if gate_record.get("required_reentry_gate") is not None:
        raise GateReviewersError(
            f"gate {gate_id} has a pending required_reentry_gate={gate_record.get('required_reentry_gate')!r}"
        )


def _default_gate_ids(dispatch_plan: dict[str, Any], gate_by_id: dict[str, dict[str, Any]]) -> list[str]:
    configured = _configured_gate_ids(dispatch_plan)
    result = []
    for gate_id in GATE_IDS:
        if gate_id not in configured:
            continue
        gate_record = gate_by_id.get(gate_id)
        if gate_record is None:
            continue
        if gate_record.get("applicability") != "applicable":
            continue
        if gate_record.get("status") == "invalidated":
            continue
        if gate_record.get("required_reentry_gate") is not None:
            continue
        result.append(gate_id)
    return result


# --------------------------------------------------------------------------
# Self-approval / independence: `is_gate_self_approval` is now shared via
# `agentic_sdlc/__init__.py` (also used by `gate_issues.py`), imported above.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Plan building
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Motivation:
    gate_id: str
    authority_id: str
    role: str
    authority_type: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "authority_id": self.authority_id,
            "role": self.role,
            "authority_type": self.authority_type,
        }


@dataclass(frozen=True)
class SkippedEntry:
    gate_id: str
    authority_id: str
    reason: str
    rationale: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"gate_id": self.gate_id, "authority_id": self.authority_id, "reason": self.reason, "rationale": self.rationale}


@dataclass(frozen=True)
class RefusalEntry:
    gate_id: str
    authority_id: str
    reason: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"gate_id": self.gate_id, "authority_id": self.authority_id, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class PoisonCause:
    gate_id: str
    authority_id: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"gate_id": self.gate_id, "authority_id": self.authority_id, "reason": self.reason}


def build_plan(
    *, gate_ids: list[str], record: dict[str, Any], authorities: dict[str, Any],
    pr_author_login: str | None, as_bot_login: str,
    resolve_login: Callable[[dict[str, Any]], str | None] = authority_github_login,
    no_binding_reason: str = "no-github-binding",
    author_conflict_reason: str = "pr-author-conflict",
) -> tuple[
    dict[str, list[Motivation]], dict[str, str], dict[str, PoisonCause], list[SkippedEntry], list[RefusalEntry],
]:
    """Returns `(motivations_by_login, login_display, poisoned_by_login,
    skipped, refusals)`, all keyed by lower-cased login where applicable.
    `login_display` preserves the first-seen casing of each login for
    reporting; grouping/comparison itself is always case-insensitive.

    Forge-agnostic by construction (eligibility, self-approval/independence,
    and PR-wide/MR-wide poisoning are the same policy regardless of forge --
    only *how a login/username is resolved* and *which reason codes name the
    binding-missing / author-conflict cases* differ). `gate_reviewers_gitlab.py`
    calls this directly with `resolve_login=authority_gitlab_username`,
    `no_binding_reason="no-gitlab-binding"`, `author_conflict_reason="mr-author-conflict"`
    rather than duplicating this function -- see that module's docstring."""
    gate_by_id = {g["gate_id"]: g for g in record.get("lifecycle_gates", [])}
    motivations_by_login: dict[str, list[Motivation]] = {}
    login_display: dict[str, str] = {}
    poisoned_by_login: dict[str, PoisonCause] = {}
    skipped: list[SkippedEntry] = []
    refusals: list[RefusalEntry] = []

    for gate_id in gate_ids:
        gate_record = gate_by_id.get(gate_id)
        if gate_record is None:
            raise GateReviewersError(f"gate {gate_id} not found in the run record's lifecycle_gates array")

        for requirement in gate_record.get("authority_requirements", []):
            authority_id = requirement.get("authority_id")
            applicability = requirement.get("applicability")
            authority = authorities.get(authority_id)
            role_label = requirement.get("role", authority_id)
            authority_type = requirement.get("authority_type")

            if applicability == "not-applicable":
                skipped.append(SkippedEntry(gate_id, authority_id, "not-applicable", requirement.get("rationale")))
                continue
            if applicability == "unknown":
                authority_applicability = authority.get("applicability") if isinstance(authority, dict) else None
                if authority_applicability == "not-applicable":
                    skipped.append(
                        SkippedEntry(
                            gate_id, authority_id, "authorities-not-applicable",
                            authority.get("rationale") if isinstance(authority, dict) else None,
                        )
                    )
                else:
                    refusals.append(
                        RefusalEntry(
                            gate_id, authority_id, "applicability-unknown",
                            "authority_requirements applicability is 'unknown' and authorities.json does not "
                            "mark this authority not-applicable",
                        )
                    )
                continue
            if applicability != "applicable":
                refusals.append(
                    RefusalEntry(gate_id, authority_id, "applicability-unknown", f"unrecognized applicability {applicability!r}")
                )
                continue
            if not isinstance(authority, dict):
                refusals.append(
                    RefusalEntry(gate_id, authority_id, "authority-unknown", f"role {authority_id} missing from authorities.json")
                )
                continue
            if authority.get("status") != "assigned" or not authority.get("assignee"):
                refusals.append(
                    RefusalEntry(gate_id, authority_id, "authority-unassigned", f"authority {authority_id} is not assigned")
                )
                continue

            login = resolve_login(authority)
            if not login:
                refusals.append(
                    RefusalEntry(gate_id, authority_id, no_binding_reason, f"authority {authority_id} has no login binding")
                )
                continue

            reason: str | None = None
            if is_gate_self_approval(authority.get("assignee"), gate_record):
                reason = "self-approval"
            elif pr_author_login and login.lower() == pr_author_login.lower():
                reason = author_conflict_reason
            elif as_bot_login and login.lower() == as_bot_login.lower():
                reason = "actor-is-reviewer"

            key = login.lower()
            login_display.setdefault(key, login)
            motivations_by_login.setdefault(key, []).append(Motivation(gate_id, authority_id, role_label, authority_type))

            if reason is not None:
                detail = f"authority {authority_id}'s resolved login {login!r} is withheld from {gate_id} ({reason})"
                refusals.append(RefusalEntry(gate_id, authority_id, reason, detail))
                # First independence conflict for this login wins as the
                # reported cause; later conflicts for the same login are
                # still recorded in refusals[] above but do not replace it.
                poisoned_by_login.setdefault(key, PoisonCause(gate_id, authority_id, reason))

    return motivations_by_login, login_display, poisoned_by_login, skipped, refusals


# --------------------------------------------------------------------------
# Existence / review classification
# --------------------------------------------------------------------------


def classify_login(*, login: str, requested_reviewers: set[str], reviews: list[dict[str, Any]], head_sha: str) -> str:
    """Priority: already-reviewed > review-stale > already-requested >
    to-request. A dismissed review never counts (`review-dismissed` is not
    a distinct reason code -- it simply falls through to whichever of the
    remaining checks applies, per this module's docstring)."""
    normalized_login = login.lower()
    normalized_head = normalize_commit_sha(head_sha)
    non_dismissed = [
        review
        for review in reviews
        if isinstance(review.get("user"), dict)
        and isinstance(review["user"].get("login"), str)
        and review["user"]["login"].lower() == normalized_login
        and str(review.get("state", "")).upper() != "DISMISSED"
    ]
    if non_dismissed:
        non_dismissed.sort(key=lambda review: str(review.get("submitted_at") or ""))
        latest = non_dismissed[-1]
        review_commit = normalize_commit_sha(latest.get("commit_id"))
        if review_commit is not None and review_commit == normalized_head:
            return "already-reviewed"
        return "review-stale"
    if normalized_login in requested_reviewers:
        return "already-requested"
    return "to-request"


# --------------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------------


def run(
    *, root: Path, task_id: str, repo: str, pr: int, as_bot: str, gates: list[str] | None,
    allow_classification: str | None,
) -> dict[str, Any]:
    root = Path(root)
    overlay_dir = confined_path(root, OVERLAY)
    record_path = confined_path(root, OVERLAY, "runs", task_id, "run-record.json")
    dispatch_path = confined_path(root, OVERLAY, "runs", task_id, "dispatch-plan.json")
    record = load_json(record_path)
    dispatch_plan = load_json(dispatch_path)
    authorities = load_json(overlay_dir / "authorities.json")
    # lifecycle_contracts is loaded for parity with gate_issues.run() and
    # to fail closed on a corrupted bundled contract, even though this
    # report does not currently render gate name/phase text anywhere.
    load_json(CONTRACTS / "lifecycle-gates.json")
    gate_by_id = {item["gate_id"]: item for item in record.get("lifecycle_gates", [])}

    if allow_classification is None or allow_classification != record.get("classification"):
        raise GateReviewersError(
            "--allow-classification must be supplied and exactly match the task's classification "
            f"(got {allow_classification!r}, task classification is {record.get('classification')!r})"
        )

    if gates:
        gate_ids = []
        for gate_id in gates:
            check_gate_eligibility(gate_id, dispatch_plan, gate_by_id.get(gate_id))
            gate_ids.append(gate_id)
    else:
        gate_ids = _default_gate_ids(dispatch_plan, gate_by_id)

    try:
        verified_login = github_write.verify_github_identity(as_bot)
    except ValueError as exc:
        raise GateReviewersError(str(exc)) from exc

    try:
        pr_raw = github_write.fetch_github_pr(repo, pr)
    except (github_write.PRNotFound, ValueError) as exc:
        raise GateReviewersError(str(exc)) from exc
    if not isinstance(pr_raw, dict):
        raise GateReviewersError(f"malformed PR response for {repo}#{pr}")

    state = pr_raw.get("state")
    merged = bool(pr_raw.get("merged"))
    if state == "closed" or merged:
        raise GateReviewersError(f"GitHub PR {repo}#{pr} is closed or merged (state={state!r}, merged={merged})")

    base = pr_raw.get("base") if isinstance(pr_raw.get("base"), dict) else {}
    base_repo = base.get("repo") if isinstance(base.get("repo"), dict) else {}
    base_full_name = base_repo.get("full_name")
    if not isinstance(base_full_name, str) or base_full_name.lower() != repo.lower():
        raise GateReviewersError(
            f"GitHub PR {repo}#{pr}'s base repository ({base_full_name!r}) does not match --repo {repo!r}"
        )

    head = pr_raw.get("head") if isinstance(pr_raw.get("head"), dict) else {}
    head_sha = head.get("sha")
    if not isinstance(head_sha, str) or not head_sha:
        raise GateReviewersError(f"GitHub PR {repo}#{pr} response is missing head.sha")

    draft = bool(pr_raw.get("draft", False))
    pr_user = pr_raw.get("user") if isinstance(pr_raw.get("user"), dict) else {}
    pr_author_login = pr_user.get("login") if isinstance(pr_user.get("login"), str) else None

    motivations_by_login, login_display, poisoned_by_login, skipped, refusals = build_plan(
        gate_ids=gate_ids, record=record, authorities=authorities,
        pr_author_login=pr_author_login, as_bot_login=verified_login,
    )

    try:
        requested_logins = {login.lower() for login in github_write.fetch_requested_reviewers(repo, pr)}
    except ValueError as exc:
        raise GateReviewersError(str(exc)) from exc
    try:
        reviews = fetch_github_pr_reviews(repo, pr)
    except ValueError as exc:
        raise GateReviewersError(str(exc)) from exc

    reviewers_report: list[dict[str, Any]] = []
    for key, motivations in motivations_by_login.items():
        display_login = login_display[key]
        motivation_dicts = [m.as_dict() for m in motivations]

        if key in poisoned_by_login:
            reviewers_report.append({
                "login": display_login,
                "classification": "withheld-conflict",
                "motivations": motivation_dicts,
                "withheld_cause": poisoned_by_login[key].as_dict(),
            })
            continue

        try:
            exists = github_write.check_github_user_exists(display_login)
        except ValueError as exc:
            raise GateReviewersError(str(exc)) from exc
        if not exists:
            reviewers_report.append({
                "login": display_login, "classification": "github-user-unresolved",
                "motivations": motivation_dicts, "withheld_cause": None,
            })
            continue

        try:
            is_collaborator = github_write.check_github_collaborator(repo, display_login)
        except ValueError as exc:
            raise GateReviewersError(str(exc)) from exc
        if not is_collaborator:
            reviewers_report.append({
                "login": display_login, "classification": "not-a-collaborator",
                "motivations": motivation_dicts, "withheld_cause": None,
            })
            continue

        classification = classify_login(
            login=display_login, requested_reviewers=requested_logins, reviews=reviews, head_sha=head_sha,
        )
        reviewers_report.append({
            "login": display_login, "classification": classification,
            "motivations": motivation_dicts, "withheld_cause": None,
        })

    reviewers_report.sort(key=lambda item: item["login"].lower())

    summary: dict[str, int] = {}
    for item in reviewers_report:
        summary[item["classification"]] = summary.get(item["classification"], 0) + 1

    return {
        "repo": repo,
        "pr": pr,
        "pr_head_sha": head_sha,
        "pr_draft": draft,
        "pr_author_login": pr_author_login,
        "as_bot_login": verified_login,
        "gate_ids": gate_ids,
        "reviewers": reviewers_report,
        "skipped": [entry.as_dict() for entry in skipped],
        "refusals": [entry.as_dict() for entry in refusals],
        "summary": summary,
    }
