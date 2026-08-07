"""`create-github-gate-issues` / `list-github-gate-issues`: the GitHub
mirror of `create-gate-issues` / `list-gate-issues` (`gate_issues.py`).
Same two-level granularity (one gate tracking issue per applicable
lifecycle gate, one approval issue per applicable `authority_requirements[]`
entry), same forge-is-the-source-of-truth idempotency philosophy, same
two-phase dry-run/apply digest handshake -- ported and adapted for GitHub's
issue API, which differs from GitLab's in several load-bearing ways
documented below.

## UNVERIFIED ASSUMPTIONS -- read before trusting this module's behavior

No live GitHub API verification session was available while writing this
module (no scratch-repo credentials; gated by
`roster/shared/agent-autonomy.yaml`'s `shared_system_access` policy in the
task that produced this file). The idempotency mechanism, label
auto-creation defense, and secondary-rate-limit detection below are
implemented **as documented assumptions, fail-closed, not verified facts**
-- the same posture `gitlab_write._is_link_unavailable_error`'s own
docstring already takes toward its own stderr-format assumption. See
`github_issue_write.py`'s module docstring for the full V3/V4/V5 writeup;
summarized here:

- **V3**: `GET /repos/{owner}/{repo}/issues?labels=<marker>&state=all&per_page=20`
  is assumed to accept `state=all` together with `labels=`. If this is
  rejected by the live API, the documented (not-yet-implemented) fallback is
  two separate calls (`state=open`, `state=closed`) unioned by the caller.
- **V4**: whether GitHub auto-creates a label on issue-create is unverified;
  `github_issue_write.ensure_label()` runs before every creation regardless,
  as cheap insurance.
- **V5**: `github_issue_write._is_secondary_rate_limit_error` pattern-matches
  GitHub's documented secondary-rate-limit message text; the exact stderr
  shape has not been observed against a live throttled response.

## Idempotency mechanism -- marker label alone, never the Search API

Existence is determined by
`github_issue_write.search_issues_by_label(repo, <its own marker label>)` --
`GET /repos/{owner}/{repo}/issues?labels=<marker>&state=all&per_page=20`.
Unlike `gate_issues.py`'s `search_gitlab_issues_by_labels(project,
[FIXED_LABEL, own_label])` (a two-label pair), this module queries the
marker label ALONE; the `FIXED_LABEL` anchor is validated separately on any
match (`_validate_matched_issue`, mirroring `gate_issues.py`'s function of
the same name). GitHub's full-text issue-search endpoint is never called
anywhere in this module or `github_issue_write.py` -- see
`test_gate_issues_github.py`'s source-inspection regression test asserting
neither module contains the literal search-endpoint path fragments this module must never call.

Mandatory result post-processing, applied in this exact order, all
fail-closed:

1. Any returned entry carrying a `pull_request` key blocks the run
   (`label-on-pull-request`) -- GitHub's issue-list endpoint returns pull
   requests too, and this module's marker label can never legitimately be
   on a PR, so a match here is treated as tampering/collision, never
   filtered past silently.
2. Label comparison is **case-insensitive** throughout this module --
   GitHub label names are unique on a repo case-insensitively, unlike
   `gate_issues.py`'s exact-match set comparison against GitLab labels. This
   is a deliberate, documented deviation from the GitLab module, not an
   oversight.
3. 0 matches creates; 1 match reuses (after the same anchor-label +
   author-identity validation `gate_issues.py`'s `_validate_matched_issue`
   performs); >1 matches blocks (ambiguous identity).
4. A single page returning exactly `per_page` (20) entries blocks
   (`result-cap-exceeded`) -- this module never paginates; an ambiguity this
   large needs a human, not auto-resolution.

## Repository pre-flight (real added scope beyond GitLab parity)

Before any write, `GET /repos/{owner}/{repo}` is fetched and checked:
`has_issues == false` is a structural error (issues disabled); a public
repo without `--allow-public-repo` is also a structural error. GitHub has no
per-issue `confidential` flag the way GitLab does (`gate_issues.py`'s
post-creation verification checks `confidential is False`) -- gate/approval
issues carry gate names, phases, sanitized rationale, and authority role
labels, so this repository-level check is this module's data-minimization
substitute.

## Markers/labels (extends `gate_issues.py`'s domain-separation table)

| Kind | Marker input (NUL-separated, sha256, `[:16]`) | Label prefix |
|---|---|---|
| Gate issue (GitLab) | `"gate"`, `task_id`, `gate_id` | `agentic-sdlc-gate-` |
| Approval issue (GitLab) | `"approval"`, `task_id`, `gate_id`, `authority_id` | `agentic-sdlc-approval-` |
| Gate issue (GitHub) | `"github-gate"`, `task_id`, `gate_id` | `agentic-sdlc-gh-gate-` |
| Approval issue (GitHub) | `"github-approval"`, `task_id`, `gate_id`, `authority_id` | `agentic-sdlc-gh-approval-` |
| Gate-status comment (`gate_status.py`) | `"gate-status"`, `task_id` | n/a -- HTML comment, not a label |

The GitHub marker inputs' `"github-gate"`/`"github-approval"` leading
literal tags are disjoint from the GitLab module's `"gate"`/`"approval"`
tags and from the LangGraph engine's untagged `requirement_issues.compute_marker`,
for the same reasoning `gate_issues.py`'s own docstring gives for its pair.
`task_id` is never emitted raw here either -- only `task_hash(task_id)`.

## Link primitive -- description cross-reference only, no link-type selection flag

Every approval issue's description carries a module-emitted
`> parent {owner}/{repo}#{gate_issue_number}` line -- GitHub renders this as
a live cross-reference. This is the only linkage in v1: there is no
link-type selection flag, no opt-in enhancement, and no GitHub Issue Links
API equivalent call anywhere in this module (GitHub has no separate Issue
Links API the way GitLab does). `test_gate_issues_github.py` asserts the
GitLab-only link-type CLI flag is rejected by argparse as an unrecognized
argument and that neither
any issue-linking flag or relationship-type token appears anywhere in this module's source.

## Assignee drift and the GitHub-specific silent-drop failure mode

On reuse, this module compares GitHub's current `assignees` against the
resolved expected login, recording `drift: "assignee_changed"` (report-only
unless `--reconcile-assignees`, mirroring `gate_issues.py`). GitHub has a
failure mode GitLab does not: assigning a non-collaborator to an issue is
silently accepted by some API paths but the assignment never actually takes
-- a "drop", not a rejection. Two-layer defense: (1) a pre-check
(`github_write.check_github_user_exists`/`check_github_collaborator`)
before creating an approval issue -- failure is a per-authority refusal
(`github-user-unresolved`/`not-a-collaborator`), and the batch continues;
(2) the post-create/post-PATCH re-fetch-and-verify step is the backstop for
a TOCTOU race between the pre-check and the actual write -- a mismatch
there **blocks** the run, it never just reports.

## Self-approval / independence

Uses the shared `agentic_sdlc.is_gate_self_approval` (see that function's
docstring) -- identical semantics to `gate_issues.py`, no local copy.

## Eligibility -- intentionally still a local copy, not shared, for v1

`check_gate_eligibility`/`_default_gate_ids` below are a local copy of
`gate_issues.py`'s functions of the same name (byte-for-byte rule set:
gate in the dispatch plan's configured set, `applicability == "applicable"`,
`status != "invalidated"`, no pending `required_reentry_gate`). A future
consolidation could extract a shared, exception-generic eligibility checker
both `gate_issues.py` and this module call into -- deliberately out of
scope for this task to keep its blast radius contained (mirrors
`gate_reviewers.py`'s own "local copy for now" framing for the exact same
functions).

## Strictly orthogonal to the approval adapters

Like `gate_issues.py`, this module never imports `record_github_approval`,
`record_gitlab_approval`, `record_gate_decision`, `record_gitlab_issue_link`,
or `record_github_issue_link` from the parent `agentic_sdlc` package, and
never writes `run-record.json`, `dispatch-plan.json`, or `authorities.json`
-- it only reads them, plus its own sidecar ledger file.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import (
    CONTRACTS,
    GATE_IDS,
    OVERLAY,
    authority_github_login,
    confined_path,
    fingerprint,
    is_gate_self_approval,
    load_json,
    now,
)
from . import _forge_ledger, _forge_text, github_issue_write, github_write

MAX_ISSUES_PER_RUN = 40
LEDGER_SCHEMA_VERSION = 1

FORGE_GITHUB = "github"
_LEDGER_FILENAME = "gate-issues-github.json"
_LOCK_FILENAME = "gate-issues-github.lock"

FIXED_LABEL = github_issue_write.FIXED_LABEL
GATE_LABEL_PREFIX = "agentic-sdlc-gh-gate-"
APPROVAL_LABEL_PREFIX = "agentic-sdlc-gh-approval-"

_LABEL_CHARSET_RE = _forge_text._LABEL_CHARSET_RE
_PROVENANCE_LINE = _forge_text._PROVENANCE_LINE
_REF_LINE_PREFIX = _forge_text._REF_LINE_PREFIX
_PARENT_LINE_PREFIX = _forge_text._PARENT_LINE_PREFIX

task_hash = _forge_text.task_hash

_ADVISORY_TEMPLATE = (
    "{provenance} Tracking artifact only — closing this issue is not approval evidence "
    "and does not approve {gate_id}. The approver must not be a preparer or the independent "
    "verifier of this gate. Record approval via `agentic-sdlc approve-from-github-pr` or "
    "`agentic-sdlc decide`."
)

# No ambiguous-match reason code for user lookups: GET /users/{login} is exact-match,
# unlike GitLab's search-based lookup -- see github_write.check_github_user_exists.
REASON_CODES = frozenset({
    "authority-unknown",
    "authority-unassigned",
    "applicability-unknown",
    "self-approval",
    "no-github-binding",
    "github-user-unresolved",
    "not-a-collaborator",
})


class GateIssuesGithubError(ValueError):
    """Structural/policy failure -- CLI maps this to exit code 1."""


class GateIssuesGithubBlocked(ValueError):
    """Needs human resolution -- CLI maps this to exit code 2."""


class _ApprovalRefusal(Exception):
    """Internal control-flow signal only: an approval candidate turned out
    to be unresolvable once a live GitHub call was made. Caught by run()
    and folded into refusals[] -- never escapes this module."""

    def __init__(self, gate_id: str, authority_id: str, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.gate_id = gate_id
        self.authority_id = authority_id
        self.reason = reason
        self.detail = detail


# --------------------------------------------------------------------------
# Identity, markers, labels
# --------------------------------------------------------------------------


def compute_gate_marker(task_id: str, gate_id: str) -> str:
    digest = hashlib.sha256(f"github-gate\x00{task_id}\x00{gate_id}".encode("utf-8")).hexdigest()
    return digest[:16]


def compute_approval_marker(task_id: str, gate_id: str, authority_id: str) -> str:
    digest = hashlib.sha256(f"github-approval\x00{task_id}\x00{gate_id}\x00{authority_id}".encode("utf-8")).hexdigest()
    return digest[:16]


def gate_label(marker: str) -> str:
    label = f"{GATE_LABEL_PREFIX}{marker}"
    if not _LABEL_CHARSET_RE.fullmatch(label):
        raise GateIssuesGithubError(f"computed label {label!r} violates the [a-z0-9-] label charset")
    return label


def approval_label(marker: str) -> str:
    label = f"{APPROVAL_LABEL_PREFIX}{marker}"
    if not _LABEL_CHARSET_RE.fullmatch(label):
        raise GateIssuesGithubError(f"computed label {label!r} violates the [a-z0-9-] label charset")
    return label


def sanitize_free_text(text: str, field_name: str) -> str:
    try:
        return _forge_text.sanitize_free_text(text, field_name)
    except _forge_text.ForgeTextError as exc:
        raise GateIssuesGithubError(str(exc)) from exc


def sanitize_title_text(text: str, field_name: str) -> str:
    try:
        return _forge_text.sanitize_title_text(text, field_name)
    except _forge_text.ForgeTextError as exc:
        raise GateIssuesGithubError(str(exc)) from exc


# --------------------------------------------------------------------------
# Title/description rendering
# --------------------------------------------------------------------------


def gate_issue_title(task_id: str, gate_id: str, gate_name: str) -> str:
    raw = f"[agentic-sdlc] {gate_id} {gate_name} ({task_hash(task_id)})"
    return sanitize_title_text(raw, f"{gate_id} gate issue title")


def approval_issue_title(task_id: str, gate_id: str, gate_name: str, role: str) -> str:
    raw = f"[agentic-sdlc] Approve {gate_id} {gate_name} - {role} ({task_hash(task_id)})"
    return sanitize_title_text(raw, f"{gate_id} approval issue title")


def render_gate_description(
    task_id: str, gate_id: str, gate_name: str, phase: str, human_only: bool, marker: str,
    rationale: str | None, scope_text: str | None,
) -> str:
    lines = [
        f"{_PROVENANCE_LINE} Not a human-authored artifact. Not approval evidence.",
        f"{_REF_LINE_PREFIX}{task_hash(task_id)}/{gate_id}/{marker}",
        "",
        f"Gate: {gate_id} {gate_name} (phase: {phase})",
    ]
    if rationale:
        lines.append(
            f"Applicability rationale: {sanitize_free_text(rationale, f'{gate_id} applicability_rationale')}"
        )
    if human_only:
        lines.append(
            "This is a human-only gate -- automation cannot grant it (see contracts/lifecycle-gates.json "
            "human_only)."
        )
    if scope_text:
        lines.append(f"Scope: {sanitize_free_text(scope_text, f'{gate_id} scope')}")
    return "\n".join(lines) + "\n"


def render_approval_description(
    task_id: str, gate_id: str, marker: str, repo: str, gate_issue_number: int, rationale: str | None,
) -> str:
    advisory = _ADVISORY_TEMPLATE.format(provenance=_PROVENANCE_LINE, gate_id=gate_id)
    lines = [
        advisory,
        f"{_REF_LINE_PREFIX}{task_hash(task_id)}/{gate_id}/{marker}",
        f"{_PARENT_LINE_PREFIX}{repo}#{gate_issue_number}",
        "",
    ]
    if rationale:
        lines.append(sanitize_free_text(rationale, f"{gate_id} authority rationale"))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Eligibility (local copy of gate_issues.py's rules; see module docstring
# for why this is not a shared import in v1)
# --------------------------------------------------------------------------


def _configured_gate_ids(dispatch_plan: dict[str, Any]) -> set[str]:
    return {
        item.get("gate_id")
        for item in dispatch_plan.get("gate_dispatch", [])
        if item.get("status") == "required"
    }


def check_gate_eligibility(gate_id: str, dispatch_plan: dict[str, Any], gate_record: dict[str, Any] | None) -> None:
    if gate_id not in GATE_IDS:
        raise GateIssuesGithubError(f"unknown gate id: {gate_id!r}")
    if gate_record is None:
        raise GateIssuesGithubError(
            f"gate {gate_id} not found in the run record's lifecycle_gates array "
            "(lookup is by gate_id, not index; the array must contain exactly G1-G10)"
        )
    if gate_id not in _configured_gate_ids(dispatch_plan):
        raise GateIssuesGithubBlocked(f"gate {gate_id} is not part of the task's configured (dispatch-plan) gate set")
    if gate_record.get("applicability") != "applicable":
        raise GateIssuesGithubBlocked(
            f"gate {gate_id} applicability is {gate_record.get('applicability')!r}, not 'applicable'"
        )
    if gate_record.get("status") == "invalidated":
        raise GateIssuesGithubBlocked(f"gate {gate_id} status is 'invalidated'")
    if gate_record.get("required_reentry_gate") is not None:
        raise GateIssuesGithubBlocked(
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
# Plan building (pure; shared by dry-run and apply, re-run before every
# apply-mode item to detect concurrent state changes)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GatePlan:
    gate_id: str
    gate_name: str
    phase: str
    human_only: bool
    marker: str
    label: str
    title: str
    description: str


@dataclass(frozen=True)
class ApprovalCandidate:
    gate_id: str
    authority_id: str
    role: str
    marker: str
    label: str
    title: str
    login: str
    rationale: str | None


@dataclass(frozen=True)
class SkippedEntry:
    gate_id: str
    authority_id: str
    reason: str
    rationale: str | None


@dataclass(frozen=True)
class RefusalEntry:
    gate_id: str
    authority_id: str
    reason: str
    detail: str


def build_plan(
    *, task_id: str, repo: str, gate_ids: list[str], record: dict[str, Any],
    authorities: dict[str, Any], dispatch_plan: dict[str, Any], lifecycle_contracts: dict[str, dict[str, Any]],
    include_scope: bool, scope_text: str | None,
) -> tuple[list[GatePlan], list[ApprovalCandidate], list[SkippedEntry], list[RefusalEntry], dict[str, Any]]:
    gate_by_id = {g["gate_id"]: g for g in record.get("lifecycle_gates", [])}
    gate_plans: list[GatePlan] = []
    approval_candidates: list[ApprovalCandidate] = []
    skipped: list[SkippedEntry] = []
    refusals: list[RefusalEntry] = []
    per_gate_digest: dict[str, Any] = {}

    for gate_id in gate_ids:
        gate_record = gate_by_id.get(gate_id)
        if gate_record is None:
            raise GateIssuesGithubError(f"gate {gate_id} not found in the run record's lifecycle_gates array")
        contract = lifecycle_contracts.get(gate_id, {})
        gate_name = contract.get("name", gate_id)
        phase = contract.get("phase", "")
        human_only = bool(contract.get("human_only"))

        marker = compute_gate_marker(task_id, gate_id)
        label = gate_label(marker)
        title = gate_issue_title(task_id, gate_id, gate_name)
        description = render_gate_description(
            task_id, gate_id, gate_name, phase, human_only, marker,
            gate_record.get("applicability_rationale"),
            scope_text if include_scope else None,
        )
        gate_plans.append(GatePlan(gate_id, gate_name, phase, human_only, marker, label, title, description))

        authority_requirements = gate_record.get("authority_requirements", [])
        resolved_logins: dict[str, str | None] = {}
        for requirement in authority_requirements:
            authority_id = requirement.get("authority_id")
            authority = authorities.get(authority_id)
            resolved_logins[authority_id] = (
                authority_github_login(authority) if isinstance(authority, dict) else None
            )

        for requirement in authority_requirements:
            authority_id = requirement.get("authority_id")
            applicability = requirement.get("applicability")
            authority = authorities.get(authority_id)
            role_label = requirement.get("role", authority_id)

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
            login = resolved_logins.get(authority_id)
            if not login:
                refusals.append(
                    RefusalEntry(gate_id, authority_id, "no-github-binding", f"authority {authority_id} has no GitHub login binding")
                )
                continue
            if is_gate_self_approval(authority.get("assignee"), gate_record):
                refusals.append(
                    RefusalEntry(
                        gate_id, authority_id, "self-approval",
                        f"authority {authority_id}'s assignee is a preparer or the independent verifier of {gate_id}",
                    )
                )
                continue
            approval_marker = compute_approval_marker(task_id, gate_id, authority_id)
            approval_candidates.append(
                ApprovalCandidate(
                    gate_id=gate_id,
                    authority_id=authority_id,
                    role=role_label,
                    marker=approval_marker,
                    label=approval_label(approval_marker),
                    title=approval_issue_title(task_id, gate_id, gate_name, role_label),
                    login=login,
                    rationale=requirement.get("rationale"),
                )
            )

        per_gate_digest[gate_id] = {
            "applicability": gate_record.get("applicability"),
            "applicability_rationale": gate_record.get("applicability_rationale"),
            "status": gate_record.get("status"),
            "required_reentry_gate": gate_record.get("required_reentry_gate"),
            "authority_requirements": [
                {
                    "authority_id": requirement.get("authority_id"),
                    "applicability": requirement.get("applicability"),
                    "rationale": requirement.get("rationale"),
                }
                for requirement in authority_requirements
            ],
            "resolved_logins": resolved_logins,
        }

    total = len(gate_plans) + len(approval_candidates)
    if total > MAX_ISSUES_PER_RUN:
        raise GateIssuesGithubError(
            f"planned issue count {total} exceeds MAX_ISSUES_PER_RUN={MAX_ISSUES_PER_RUN} -- aborting rather "
            "than truncating"
        )

    return gate_plans, approval_candidates, skipped, refusals, per_gate_digest


def compute_plan_digest(
    *, task_id: str, repo: str, gate_ids: list[str], dispatch_fingerprint_value: str | None,
    per_gate: dict[str, Any], disposition: str | None, classification: str | None, re_entry_count: int,
) -> str:
    payload = {
        "forge": "github",
        "task_id": task_id,
        "repo": repo,
        "gate_ids": list(gate_ids),
        "dispatch_fingerprint": dispatch_fingerprint_value,
        "per_gate": per_gate,
        "eligibility": {
            "disposition": disposition,
            "classification": classification,
            "re_entry_count": re_entry_count,
        },
    }
    return fingerprint(payload)


# --------------------------------------------------------------------------
# Sidecar ledger (diagnostics only, never trusted for existence)
# --------------------------------------------------------------------------


def _ledger_path(root: Path, task_id: str) -> Path:
    return _forge_ledger.ledger_path(Path(root), OVERLAY, task_id, _LEDGER_FILENAME)


def _lock_path(root: Path, task_id: str) -> Path:
    return _forge_ledger.lock_path(Path(root), OVERLAY, task_id, _LOCK_FILENAME)


def _empty_ledger(task_id: str) -> dict[str, Any]:
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "task_id": task_id,
        "repo": None,
        "bot_login": None,
        "mocked": False,
        "entries": {},
    }


def read_ledger(root: Path, task_id: str) -> dict[str, Any]:
    path = _ledger_path(Path(root), task_id)
    if not path.is_file():
        return _empty_ledger(task_id)
    return json.loads(path.read_text(encoding="utf-8"))


def write_ledger(root: Path, task_id: str, ledger: dict[str, Any]) -> None:
    path = _ledger_path(Path(root), task_id)
    _forge_ledger.write_ledger_file(path, ledger, tmp_prefix=".gate-issues-github.")


def acquire_lock(root: Path, task_id: str, *, break_lock: bool) -> Path:
    path = _lock_path(Path(root), task_id)
    try:
        return _forge_ledger.acquire_lock_file(path, break_lock=break_lock)
    except _forge_ledger.LedgerLockHeld as exc:
        raise GateIssuesGithubBlocked(str(exc)) from None


def release_lock(path: Path) -> None:
    _forge_ledger.release_lock_file(path)


# --------------------------------------------------------------------------
# Reuse validation / raw-entry helpers
# --------------------------------------------------------------------------


def _raw_issue_labels(entry: dict[str, Any]) -> list[str]:
    labels_raw = entry.get("labels")
    result: list[str] = []
    if isinstance(labels_raw, list):
        for item in labels_raw:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                result.append(item["name"])
            elif isinstance(item, str):
                result.append(item)
    return result


def _validate_matched_issue(entry: dict[str, Any], *, own_label: str, foreign_prefix: str, context: str) -> None:
    labels_lower = {label.lower() for label in _raw_issue_labels(entry)}
    if FIXED_LABEL.lower() not in labels_lower:
        raise GateIssuesGithubBlocked(f"{context}: matched issue is missing the {FIXED_LABEL!r} anchor label")
    if own_label.lower() not in labels_lower:
        raise GateIssuesGithubBlocked(f"{context}: matched issue is missing its own label {own_label!r}")
    foreign = {
        label for label in labels_lower
        if label.startswith(foreign_prefix.lower()) and label != own_label.lower()
    }
    if foreign:
        raise GateIssuesGithubBlocked(
            f"{context}: matched issue carries a foreign label {sorted(foreign)} -- possible mismatch/poisoned issue"
        )


def _check_search_results(matches: list[dict[str, Any]], *, context: str) -> None:
    for entry in matches:
        if isinstance(entry, dict) and "pull_request" in entry:
            raise GateIssuesGithubBlocked(
                f"{context}: label-on-pull-request -- a matched entry carries a 'pull_request' key; this "
                "module's marker label can never legitimately be on a PR, treating this as tampering/collision"
            )
    if len(matches) == 20:
        raise GateIssuesGithubBlocked(
            f"{context}: result-cap-exceeded -- the search returned exactly 20 (per_page) entries; this "
            "module never paginates, needs human resolution"
        )
    if len(matches) > 1:
        raise GateIssuesGithubBlocked(
            f"{context}: {len(matches)} issues matched -- ambiguous identity, needs human resolution"
        )


# --------------------------------------------------------------------------
# Mutation delay sequencing (V5) -- see github_issue_write.py's module
# docstring. Applied between mutative calls only, never before the first,
# never during dry-run (dry-run never reaches this code path at all).
# --------------------------------------------------------------------------


class _MutationState:
    def __init__(self) -> None:
        self.count = 0

    def before_mutation(self) -> None:
        if self.count > 0:
            github_issue_write.delay_between_mutations()
        self.count += 1


# --------------------------------------------------------------------------
# Per-issue processing
# --------------------------------------------------------------------------


def _process_gate_issue(
    root: Path, task_id: str, repo: str, gp: GatePlan, ledger: dict[str, Any], *,
    bot_login: str, mocked: bool, mutation_state: _MutationState,
) -> dict[str, Any]:
    try:
        return _process_gate_issue_inner(
            root, task_id, repo, gp, ledger, bot_login=bot_login, mocked=mocked, mutation_state=mutation_state
        )
    except (GateIssuesGithubError, GateIssuesGithubBlocked):
        raise
    except ValueError as exc:
        raise GateIssuesGithubError(f"gate {gp.gate_id!r}: {exc}") from exc


def _process_gate_issue_inner(
    root: Path, task_id: str, repo: str, gp: GatePlan, ledger: dict[str, Any], *,
    bot_login: str, mocked: bool, mutation_state: _MutationState,
) -> dict[str, Any]:
    entry_key = gp.gate_id
    context = f"gate {gp.gate_id}"
    matches = github_issue_write.search_issues_by_label(repo, gp.label)
    _check_search_results(matches, context=context)

    if len(matches) == 1:
        entry = matches[0]
        _validate_matched_issue(entry, own_label=gp.label, foreign_prefix=GATE_LABEL_PREFIX, context=context)
        number = entry.get("number")
        verification = github_issue_write.fetch_issue_verification(repo, number)
        verified_author = (verification.get("author_login") or "").lower()
        if verified_author != bot_login.lower():
            entry_record = {
                "kind": "gate", "gate_id": gp.gate_id, "marker": gp.marker, "status": "suspect",
                "issue_number": number, "issue_state": verification.get("state"),
                "attempted_at": now(), "recorded_at": now(),
                "detail": "matched issue author does not match the verified bot identity",
            }
            ledger["entries"][entry_key] = entry_record
            ledger["mocked"] = mocked
            write_ledger(root, task_id, ledger)
            raise GateIssuesGithubBlocked(
                f"{context}: matched issue's author does not match the verified bot identity -- refusing to "
                "reuse, needs human resolution"
            )
        entry_record = {
            "kind": "gate", "gate_id": gp.gate_id, "marker": gp.marker, "status": "reused",
            "issue_number": number, "issue_state": verification.get("state"),
            "attempted_at": now(), "recorded_at": now(), "detail": None,
        }
        ledger["entries"][entry_key] = entry_record
        ledger["mocked"] = mocked
        write_ledger(root, task_id, ledger)
        return {"gate_id": gp.gate_id, "status": "reused", "issue_number": number, "issue_state": verification.get("state")}

    entry_record = {
        "kind": "gate", "gate_id": gp.gate_id, "marker": gp.marker, "status": "creating",
        "issue_number": None, "issue_state": None, "attempted_at": now(), "recorded_at": None, "detail": None,
    }
    ledger["entries"][entry_key] = entry_record
    ledger["mocked"] = mocked
    write_ledger(root, task_id, ledger)  # BEFORE any mutative GitHub call.

    mutation_state.before_mutation()
    github_issue_write.ensure_label(repo, gp.label)
    mutation_state.before_mutation()
    number = github_issue_write.create_issue(repo, gp.title, gp.description, [FIXED_LABEL, gp.label])
    verification = github_issue_write.fetch_issue_verification(repo, number)

    failures: list[str] = []
    if verification.get("title") != gp.title:
        failures.append("title")
    if verification.get("state") != "open":
        failures.append("state")
    if {label.lower() for label in verification.get("labels") or []} != {FIXED_LABEL.lower(), gp.label.lower()}:
        failures.append("labels")
    if len(verification.get("assignees") or []) != 0:
        failures.append("assignees")
    if (verification.get("repo_from_url") or "").lower() != repo.lower():
        failures.append("repo_from_url")
    if (verification.get("author_login") or "").lower() != bot_login.lower():
        failures.append("author_login")
    if verification.get("has_pull_request_key"):
        failures.append("has_pull_request_key")

    if failures:
        entry_record = dict(entry_record)
        entry_record.update(status="suspect", issue_number=number, issue_state=verification.get("state"), recorded_at=now())
        entry_record["detail"] = f"post-creation verification failed: {', '.join(failures)}"
        ledger["entries"][entry_key] = entry_record
        write_ledger(root, task_id, ledger)
        raise GateIssuesGithubBlocked(
            f"{context}: post-creation verification failed ({', '.join(failures)}) -- aborting the entire run "
            "immediately"
        )

    entry_record = dict(entry_record)
    entry_record.update(status="created", issue_number=number, issue_state=verification.get("state"), recorded_at=now())
    ledger["entries"][entry_key] = entry_record
    write_ledger(root, task_id, ledger)
    return {"gate_id": gp.gate_id, "status": "created", "issue_number": number, "issue_state": verification.get("state")}


def _process_approval_issue(
    root: Path, task_id: str, repo: str, ac: ApprovalCandidate, gate_issue_number: int, ledger: dict[str, Any], *,
    bot_login: str, mocked: bool, reconcile_assignees: bool, mutation_state: _MutationState,
) -> dict[str, Any]:
    try:
        return _process_approval_issue_inner(
            root, task_id, repo, ac, gate_issue_number, ledger,
            bot_login=bot_login, mocked=mocked, reconcile_assignees=reconcile_assignees, mutation_state=mutation_state,
        )
    except (GateIssuesGithubError, GateIssuesGithubBlocked, _ApprovalRefusal):
        raise
    except ValueError as exc:
        raise GateIssuesGithubError(f"gate {ac.gate_id!r} authority {ac.authority_id!r}: {exc}") from exc


def _process_approval_issue_inner(
    root: Path, task_id: str, repo: str, ac: ApprovalCandidate, gate_issue_number: int, ledger: dict[str, Any], *,
    bot_login: str, mocked: bool, reconcile_assignees: bool, mutation_state: _MutationState,
) -> dict[str, Any]:
    entry_key = f"{ac.gate_id}/{ac.authority_id}"
    context = entry_key
    matches = github_issue_write.search_issues_by_label(repo, ac.label)
    _check_search_results(matches, context=context)

    if len(matches) == 1:
        entry = matches[0]
        _validate_matched_issue(entry, own_label=ac.label, foreign_prefix=APPROVAL_LABEL_PREFIX, context=context)
        number = entry.get("number")
        verification = github_issue_write.fetch_issue_verification(repo, number)
        verified_author = (verification.get("author_login") or "").lower()
        if verified_author != bot_login.lower():
            entry_record = {
                "kind": "approval", "gate_id": ac.gate_id, "authority_id": ac.authority_id, "marker": ac.marker,
                "status": "suspect", "issue_number": number, "issue_state": verification.get("state"),
                "attempted_at": now(), "recorded_at": now(),
                "detail": "matched issue author does not match the verified bot identity",
            }
            ledger["entries"][entry_key] = entry_record
            ledger["mocked"] = mocked
            write_ledger(root, task_id, ledger)
            raise GateIssuesGithubBlocked(
                f"{context}: matched issue's author does not match the verified bot identity -- refusing to "
                "reuse, needs human resolution"
            )

        current_assignees = [login.lower() for login in verification.get("assignees", [])]
        drift = None
        if current_assignees != [ac.login.lower()]:
            drift = "assignee_changed"
            if reconcile_assignees:
                mutation_state.before_mutation()
                github_issue_write.update_issue_assignees(repo, number, [ac.login])
                refetch = github_issue_write.fetch_issue_verification(repo, number)
                refetched_assignees = [login.lower() for login in refetch.get("assignees", [])]
                if refetched_assignees != [ac.login.lower()]:
                    entry_record = {
                        "kind": "approval", "gate_id": ac.gate_id, "authority_id": ac.authority_id,
                        "marker": ac.marker, "status": "suspect", "issue_number": number,
                        "issue_state": refetch.get("state"), "attempted_at": now(), "recorded_at": now(),
                        "detail": "PATCH assignees silently dropped the assignee on re-verification",
                    }
                    ledger["entries"][entry_key] = entry_record
                    ledger["mocked"] = mocked
                    write_ledger(root, task_id, ledger)
                    raise GateIssuesGithubBlocked(
                        f"{context}: PATCH assignees silently dropped the assignee -- refusing to report "
                        "success, needs human resolution"
                    )
                drift = "assignee_changed (reconciled)"

        entry_record = {
            "kind": "approval", "gate_id": ac.gate_id, "authority_id": ac.authority_id, "marker": ac.marker,
            "status": "reused", "issue_number": number, "issue_state": verification.get("state"),
            "attempted_at": now(), "recorded_at": now(), "detail": drift,
        }
        ledger["entries"][entry_key] = entry_record
        ledger["mocked"] = mocked
        write_ledger(root, task_id, ledger)
        return {
            "gate_id": ac.gate_id, "authority_id": ac.authority_id, "status": "reused",
            "issue_number": number, "issue_state": verification.get("state"), "drift": drift,
        }

    if not github_write.check_github_user_exists(ac.login):
        raise _ApprovalRefusal(
            ac.gate_id, ac.authority_id, "github-user-unresolved",
            f"login {ac.login!r} does not resolve to an existing GitHub user",
        )
    if not github_write.check_github_collaborator(repo, ac.login):
        raise _ApprovalRefusal(
            ac.gate_id, ac.authority_id, "not-a-collaborator",
            f"login {ac.login!r} is not a collaborator on {repo}",
        )

    entry_record = {
        "kind": "approval", "gate_id": ac.gate_id, "authority_id": ac.authority_id, "marker": ac.marker,
        "status": "creating", "issue_number": None, "issue_state": None,
        "attempted_at": now(), "recorded_at": None, "detail": None,
    }
    ledger["entries"][entry_key] = entry_record
    ledger["mocked"] = mocked
    write_ledger(root, task_id, ledger)  # BEFORE any mutative GitHub call.

    description = render_approval_description(task_id, ac.gate_id, ac.marker, repo, gate_issue_number, ac.rationale)
    mutation_state.before_mutation()
    github_issue_write.ensure_label(repo, ac.label)
    mutation_state.before_mutation()
    number = github_issue_write.create_issue(repo, ac.title, description, [FIXED_LABEL, ac.label], assignees=[ac.login])
    verification = github_issue_write.fetch_issue_verification(repo, number)

    failures: list[str] = []
    if verification.get("title") != ac.title:
        failures.append("title")
    if verification.get("state") != "open":
        failures.append("state")
    if {label.lower() for label in verification.get("labels") or []} != {FIXED_LABEL.lower(), ac.label.lower()}:
        failures.append("labels")
    if [login.lower() for login in verification.get("assignees") or []] != [ac.login.lower()]:
        failures.append("assignees")
    if (verification.get("repo_from_url") or "").lower() != repo.lower():
        failures.append("repo_from_url")
    if (verification.get("author_login") or "").lower() != bot_login.lower():
        failures.append("author_login")
    if verification.get("has_pull_request_key"):
        failures.append("has_pull_request_key")

    if failures:
        entry_record = dict(entry_record)
        entry_record.update(status="suspect", issue_number=number, issue_state=verification.get("state"), recorded_at=now())
        entry_record["detail"] = f"post-creation verification failed: {', '.join(failures)}"
        ledger["entries"][entry_key] = entry_record
        write_ledger(root, task_id, ledger)
        raise GateIssuesGithubBlocked(
            f"{context}: post-creation verification failed ({', '.join(failures)}) -- aborting the entire run "
            "immediately"
        )

    entry_record = dict(entry_record)
    entry_record.update(status="created", issue_number=number, issue_state=verification.get("state"), recorded_at=now())
    ledger["entries"][entry_key] = entry_record
    write_ledger(root, task_id, ledger)
    return {
        "gate_id": ac.gate_id, "authority_id": ac.authority_id, "status": "created",
        "issue_number": number, "issue_state": verification.get("state"), "drift": None,
    }


# --------------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------------


def _is_mocked() -> bool:
    return bool(os.environ.get(github_write.GITHUB_READ_MOCK_ENV_VAR)) or bool(
        os.environ.get(github_issue_write.GITHUB_ISSUE_MOCK_ENV_VAR)
    )


def run(
    *, root: Path, task_id: str, repo: str, as_bot: str, gates: list[str] | None,
    apply: bool, plan_digest: str | None, allow_classification: str | None,
    include_scope: bool, reconcile_assignees: bool, allow_public_repo: bool,
    break_lock: bool, i_know_this_is_mocked: bool,
) -> dict[str, Any]:
    root = Path(root)
    overlay_dir = confined_path(root, OVERLAY)
    record_path = confined_path(root, OVERLAY, "runs", task_id, "run-record.json")
    dispatch_path = confined_path(root, OVERLAY, "runs", task_id, "dispatch-plan.json")
    record = load_json(record_path)
    dispatch_plan = load_json(dispatch_path)
    authorities = load_json(overlay_dir / "authorities.json")
    lifecycle_contracts = {item["id"]: item for item in load_json(CONTRACTS / "lifecycle-gates.json")["gates"]}
    gate_by_id = {item["gate_id"]: item for item in record.get("lifecycle_gates", [])}

    if allow_classification is None or allow_classification != record.get("classification"):
        raise GateIssuesGithubError(
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

    def _build(rec: dict[str, Any], auth: dict[str, Any], plan: dict[str, Any]):
        return build_plan(
            task_id=task_id, repo=repo, gate_ids=gate_ids, record=rec, authorities=auth,
            dispatch_plan=plan, lifecycle_contracts=lifecycle_contracts, include_scope=include_scope,
            scope_text=rec.get("scope") if include_scope else None,
        )

    def _digest(rec: dict[str, Any], auth: dict[str, Any], plan: dict[str, Any], per_gate: dict[str, Any]) -> str:
        return compute_plan_digest(
            task_id=task_id, repo=repo, gate_ids=gate_ids,
            dispatch_fingerprint_value=plan.get("dispatch_fingerprint"), per_gate=per_gate,
            disposition=rec.get("disposition"), classification=rec.get("classification"),
            re_entry_count=len(rec.get("re_entry_history", [])),
        )

    gate_plans, approval_candidates, skipped, refusals, per_gate_digest = _build(record, authorities, dispatch_plan)
    digest = _digest(record, authorities, dispatch_plan, per_gate_digest)

    mocked = _is_mocked()

    if not apply:
        return {
            "mode": "dry-run",
            "plan_digest": digest,
            "repo": repo,
            "gate_ids": gate_ids,
            "mocked": mocked,
            "gate_issues": [{"gate_id": gp.gate_id, "marker": gp.marker, "label": gp.label} for gp in gate_plans],
            "approval_issues": [
                {"gate_id": ac.gate_id, "authority_id": ac.authority_id, "marker": ac.marker, "label": ac.label}
                for ac in approval_candidates
            ],
            "skipped": [
                {"gate_id": s.gate_id, "authority_id": s.authority_id, "reason": s.reason, "rationale": s.rationale}
                for s in skipped
            ],
            "refusals": [
                {"gate_id": r.gate_id, "authority_id": r.authority_id, "reason": r.reason, "detail": r.detail}
                for r in refusals
            ],
        }

    if plan_digest is None:
        raise GateIssuesGithubError("--apply requires --plan-digest (from a prior --dry-run)")
    if plan_digest != digest:
        raise GateIssuesGithubBlocked(
            f"--plan-digest mismatch: recomputed {digest!r} != supplied {plan_digest!r} -- state changed since "
            "the --dry-run this digest came from; re-run --dry-run"
        )

    if mocked and not i_know_this_is_mocked:
        raise GateIssuesGithubError(
            f"{github_write.GITHUB_READ_MOCK_ENV_VAR!r} or {github_issue_write.GITHUB_ISSUE_MOCK_ENV_VAR!r} is "
            "set but --i-know-this-is-mocked was not passed -- refusing to --apply against a mocked GitHub "
            "backend"
        )

    try:
        verified_login = github_write.verify_github_identity(as_bot)
    except ValueError as exc:
        raise GateIssuesGithubError(str(exc)) from exc

    # Repository pre-flight -- before any write (see module docstring).
    repo_info = github_issue_write.fetch_github_repo(repo)
    if repo_info.get("has_issues") is False:
        raise GateIssuesGithubError(f"issues are disabled on repository {repo!r}")
    if repo_info.get("private") is False and not allow_public_repo:
        raise GateIssuesGithubError(
            f"repository {repo!r} is public and --allow-public-repo was not passed -- gate/approval issues "
            "carry gate names, phases, sanitized rationale, and authority role labels, and GitHub has no "
            "per-issue confidential flag; pass --allow-public-repo to proceed anyway"
        )

    lock_path = acquire_lock(root, task_id, break_lock=break_lock)
    try:
        ledger = read_ledger(root, task_id)
        ledger["schema_version"] = LEDGER_SCHEMA_VERSION
        ledger["task_id"] = task_id
        ledger["repo"] = repo
        ledger["bot_login"] = verified_login
        ledger["mocked"] = mocked
        ledger.setdefault("entries", {})

        def _fresh_digest() -> str:
            fresh_record = load_json(record_path)
            fresh_dispatch = load_json(dispatch_path)
            fresh_authorities = load_json(overlay_dir / "authorities.json")
            _, _, _, _, fresh_per_gate = _build(fresh_record, fresh_authorities, fresh_dispatch)
            return _digest(fresh_record, fresh_authorities, fresh_dispatch, fresh_per_gate)

        approvals_by_gate: dict[str, list[ApprovalCandidate]] = {}
        for ac in approval_candidates:
            approvals_by_gate.setdefault(ac.gate_id, []).append(ac)

        mutation_state = _MutationState()
        gate_results = []
        approval_results = []
        run_refusals = list(refusals)

        for gp in gate_plans:
            if _fresh_digest() != plan_digest:
                raise GateIssuesGithubBlocked(
                    f"plan digest changed before gate {gp.gate_id!r} (a concurrent edit happened) -- aborting "
                    "remaining items; already-created issues are unaffected"
                )
            gate_result = _process_gate_issue(
                root, task_id, repo, gp, ledger, bot_login=verified_login, mocked=mocked, mutation_state=mutation_state
            )
            gate_results.append(gate_result)
            gate_issue_number = gate_result["issue_number"]

            for ac in approvals_by_gate.get(gp.gate_id, []):
                if _fresh_digest() != plan_digest:
                    raise GateIssuesGithubBlocked(
                        f"plan digest changed before approval {gp.gate_id}/{ac.authority_id} (a concurrent "
                        "edit happened) -- aborting remaining items; already-created issues are unaffected"
                    )
                try:
                    approval_result = _process_approval_issue(
                        root, task_id, repo, ac, gate_issue_number, ledger,
                        bot_login=verified_login, mocked=mocked, reconcile_assignees=reconcile_assignees,
                        mutation_state=mutation_state,
                    )
                except _ApprovalRefusal as refusal:
                    run_refusals.append(RefusalEntry(refusal.gate_id, refusal.authority_id, refusal.reason, refusal.detail))
                    continue
                approval_results.append(approval_result)

        drift_present = any(
            result.get("drift") and str(result["drift"]).startswith("assignee_changed") and "reconciled" not in str(result["drift"])
            for result in approval_results
        )

        return {
            "mode": "apply",
            "plan_digest": digest,
            "repo": repo,
            "gate_ids": gate_ids,
            "mocked": mocked,
            "bot_login": verified_login,
            "gate_results": gate_results,
            "approval_results": approval_results,
            "skipped": [
                {"gate_id": s.gate_id, "authority_id": s.authority_id, "reason": s.reason, "rationale": s.rationale}
                for s in skipped
            ],
            "refusals": [
                {"gate_id": r.gate_id, "authority_id": r.authority_id, "reason": r.reason, "detail": r.detail}
                for r in run_refusals
            ],
            "drift_detected": drift_present,
        }
    finally:
        release_lock(lock_path)
