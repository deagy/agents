"""`validate_run_record`: the gate-record-only residual slice of the legacy
CLI's `validate_repository` (agentic_sdlc.py, `validate_repository`
~1177-1580).

That legacy function is ~400 lines and checks far more than lifecycle-gate
invariants: a project overlay's `authorities.json` / `routing.json` /
`dispatch-plan.json` cross-checks, provider/kernel version locks, and
GitHub-review approval policy / login matching. None of those concepts
exist in this package yet (project overlays, dispatch plans, and provider
loading are explicitly Phase 2/3/4 scope per the architecture plan) -- a
1:1 port would validate a run record against files and structures this
project has never built, which would either always no-op or always fail.

This module ports **only the invariants that are meaningful purely from a
`lifecycle_gates` array** (plus the top-level JSON-Schema shape), as a pure
function of `(record, schema)` (an optional `gate_contracts` mapping may be
supplied to additionally check that an approved gate declares every
authority id its lifecycle contract expects -- see `validate_run_record`'s
docstring).

Explicitly SKIPPED (overlay- or provider-loading-dependent, out of Phase 1's
built surface -- see the accompanying task report for the full list):
authorities.json / routing.json / dispatch-plan.json cross-checks,
GitHub-review policy and login-matching checks, provider/kernel
version-lock checks, and `execution_summary` dispatch-plan-consistency
checks.

Return convention mirrors the legacy CLI's exit codes:

- `(0, [])` -- valid, and every gate that should be approved is.
- `(1, errors)` -- structurally/semantically invalid (a real defect).
- `(2, blockers)` -- structurally valid but blocked on an unresolved
  decision (e.g. an authority requirement whose applicability is still
  `"unknown"`) -- returned only when there are no hard errors.

Note on `authority_type` relabeling (legacy ~1404-1408) and the
`required_reviewers = set()` block (legacy ~1423-1428): **not** ported.
See the task report for why (the former needs the legacy `ROLE_LABELS`
constant and isn't gate-record-derived in a meaningful way for this phase;
the latter is dead/broken legacy code -- an always-empty set makes its
`role not in required_reviewers` check unconditionally fail whenever a
verifier exists, so it can't be a real invariant).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import jsonschema

ALL_GATE_IDS = [f"G{n}" for n in range(1, 11)]


def _is_valid_datetime(value: Any) -> bool:
    """Port of the legacy `is_valid_datetime` (agentic_sdlc.py ~74-81).

    Kept as an explicit hand-rolled check rather than relying solely on
    the schema's own `format: date-time` + `jsonschema.FormatChecker()`:
    verified empirically in this project's venv that `date-time` is
    *not* actually registered as a format checker here (the optional
    `rfc3339-validator` dependency the legacy CLI declares via
    `jsonschema[format]` in `requirements-validation.txt` is not part of
    this package's dependency set), so `FormatChecker()` silently
    no-ops for date-time in this environment -- it would not catch a
    malformed timestamp at all. Hand-rolling this makes the checks
    correct regardless of which optional extras happen to be installed.
    """
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _check_gate_timestamps(gate: dict[str, Any], gate_id: str, errors: list[str]) -> None:
    if gate.get("decided_at") is not None and not _is_valid_datetime(gate.get("decided_at")):
        errors.append(f"{gate_id}: decided_at {gate.get('decided_at')!r} is not a valid date-time")
    for i, approval in enumerate(gate.get("human_approvals", [])):
        if approval.get("decided_at") is not None and not _is_valid_datetime(approval.get("decided_at")):
            errors.append(
                f"{gate_id}: human_approvals[{i}].decided_at {approval.get('decided_at')!r} is not a valid date-time"
            )
    for i, invalidation in enumerate(gate.get("invalidation_history", [])):
        if not _is_valid_datetime(invalidation.get("invalidated_at")):
            errors.append(
                f"{gate_id}: invalidation_history[{i}].invalidated_at "
                f"{invalidation.get('invalidated_at')!r} is not a valid date-time"
            )
    for i, exception in enumerate(gate.get("exceptions", [])):
        if not _is_valid_datetime(exception.get("expires_at")):
            errors.append(
                f"{gate_id}: exceptions[{i}].expires_at {exception.get('expires_at')!r} is not a valid date-time"
            )


def validate_run_record(
    record: dict[str, Any],
    schema: dict[str, Any],
    gate_contracts: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, list[str]]:
    """Validate the gate-record-level invariants of a run-record dict.

    `gate_contracts` is an optional `{gate_id: lifecycle-gate-contract}`
    mapping (e.g. `{g["id"]: g for g in load_lifecycle_gates(...)}`) used
    for two checks: (1) an approved gate's `authority_requirements`
    includes every authority id its lifecycle contract expects (legacy
    ~1411-1418), and (2) a `human_only` gate (its contract sets
    `"human_only": true`, e.g. G9 in the real lifecycle contract) is
    exempted from the "must have non-empty evidence_refs/artifact_bindings"
    check, since a human_only gate legitimately has zero bound agents and
    its evidence is the human decision itself, not an agent-produced
    artifact. When `gate_contracts` is omitted, both checks are skipped
    (this keeps the function usable as a pure gate-record-only check with
    zero required inputs beyond the record and schema themselves, at the
    cost of not catching a gate that dropped an expected authority
    requirement, and of applying the strict evidence/artifact check even
    to a human_only gate in that degraded mode).

    Resolved tension (previously disclosed as an open gap, now fixed):
    an earlier draft of this function required every approved gate to
    have a non-null `independent_verifier`, which rejected legitimate
    Phase-1 records where no reviewer-kind agent is bound for a gate in
    the active profile (e.g. G8/G9/G10 in the shipped `generic` profile
    -- see `tests/test_spike.py`'s full G1-G10 happy-path test, which
    round-trips through this function). The check below is now
    conditional: *if* `independent_verifier` is present, its independence
    must be properly declared; a gate with none is not penalized for
    having none, since "does this gate's profile require a verifier at
    all" is a `gate_bindings`/profile-level decision this residual,
    gate-record-only function has no visibility into.
    """
    errors: list[str] = []
    blockers: list[str] = []

    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    for schema_error in validator.iter_errors(record):
        location = ".".join(str(part) for part in schema_error.absolute_path) or "<root>"
        errors.append(f"schema {location}: {schema_error.message}")

    gate_records = record.get("lifecycle_gates", [])
    if [gate.get("gate_id") for gate in gate_records] != ALL_GATE_IDS:
        errors.append("lifecycle_gates must be exactly G1-G10 in order")

    for i, invalidation in enumerate(record.get("re_entry_history", [])):
        if not _is_valid_datetime(invalidation.get("invalidated_at")):
            errors.append(
                f"re_entry_history[{i}].invalidated_at {invalidation.get('invalidated_at')!r} "
                "is not a valid date-time"
            )

    invalidation_started = False
    for index, gate in enumerate(gate_records):
        gate_id = gate.get("gate_id", f"<gate index {index}>")
        status = gate.get("status")
        preparers = {
            identity.get("id") for identity in gate.get("preparers", []) if isinstance(identity, dict)
        }
        verifier = gate.get("independent_verifier")

        _check_gate_timestamps(gate, gate_id, errors)

        # Verifier-is-also-a-preparer collision: meaningful regardless of
        # the gate's current status (legacy ~1356-1359).
        if isinstance(verifier, dict) and verifier.get("id") in preparers:
            errors.append(f"{gate_id}: independent_verifier is also a preparer")

        # Downstream-of-invalidation cascade (legacy ~1362-1363): once one
        # gate in sequence is invalidated, every later gate must be too.
        if invalidation_started and status != "invalidated":
            errors.append(f"{gate_id}: downstream gate must be invalidated once an earlier gate is")
        if status == "invalidated":
            invalidation_started = True
            if not gate.get("required_reentry_gate"):
                errors.append(f"{gate_id}: invalidated gate is missing required_reentry_gate")

        if status != "approved":
            continue

        # Gate order (legacy ~1388-1394): cannot be approved while an
        # earlier, applicable, non-approved gate exists before it.
        if any(
            prior.get("status") != "approved" and prior.get("applicability") != "not-applicable"
            for prior in gate_records[:index]
        ):
            errors.append(f"{gate_id}: approved before all prerequisite gates were approved")

        # Safe-approval shape (legacy ~1395-1396). A human_only gate (e.g.
        # G9 in the real generic profile) has zero bound agents by design
        # -- its "evidence" is the human decision itself, not
        # agent-produced artifacts, so evidence_refs/artifact_bindings
        # aren't required for it. Only enforced when `gate_contracts` is
        # supplied and says otherwise; without contract info this stays
        # the strict legacy-equivalent check (best-effort degraded mode).
        contract = (gate_contracts or {}).get(gate_id, {})
        is_human_only = bool(contract.get("human_only"))
        if gate.get("applicability") != "applicable":
            errors.append(f"{gate_id}: approved gate must have applicability=='applicable'")
        if not is_human_only and (not gate.get("evidence_refs") or not gate.get("artifact_bindings")):
            errors.append(
                f"{gate_id}: approved gate must have non-empty evidence_refs and artifact_bindings"
            )

        # Authority-requirements self-consistency (legacy ~1399-1420).
        requirements = gate.get("authority_requirements", [])
        requirement_ids: set[str] = set()
        unknown_ids: list[str] = []
        for requirement in requirements:
            authority_id = requirement.get("authority_id")
            if authority_id in requirement_ids:
                errors.append(f"{gate_id}: duplicate authority requirement {authority_id!r}")
            requirement_ids.add(authority_id)
            if requirement.get("applicability") == "unknown":
                unknown_ids.append(authority_id)

        if gate_contracts is not None:
            contract = gate_contracts.get(gate_id, {})
            expected_ids = set(contract.get("authority_requirements", []))
            missing = expected_ids - requirement_ids
            if missing:
                errors.append(f"{gate_id}: missing authority requirements {sorted(missing)}")

        if unknown_ids:
            # Deliberately a *blocker*, not an error: legacy classifies
            # this as an error (~1419-1420), but "an authority's
            # applicability is still unresolved" is exactly the
            # "structurally valid, blocked on an unresolved decision"
            # case this function's two-list convention exists to
            # distinguish from a hard defect.
            blockers.append(f"{gate_id}: approved with unresolved authority applicability for {sorted(unknown_ids)}")

        # Independent-verifier declaration (legacy ~1421-1422 only --
        # ~1423-1428's `required_reviewers = set()` check is dead/broken
        # legacy code, deliberately not ported; see module docstring).
        # `independent_verifier` is optional at the schema level
        # (`Identity | None`) -- whether a *given* gate's profile binds a
        # reviewer-kind agent at all is a gate_bindings/profile decision
        # this residual, gate-record-only function has no visibility into
        # (see the class docstring's disclosed tension). The invariant
        # this function CAN enforce without that information is narrower
        # than the legacy code's unconditional check: *if* a verifier is
        # present, its independence must be properly declared; a gate
        # that legitimately has no bound reviewer (e.g. G8/G9 in the real
        # generic profile) is not penalized for having none.
        if isinstance(verifier, dict) and not gate.get("independence_declaration", {}).get(
            "verifier_confirmed_not_preparer"
        ):
            errors.append(f"{gate_id}: has an independent_verifier but lacks its independence declaration")

        # Approver independence (legacy ~1442-1443): an approver must not
        # be one of the gate's preparers, nor the independent verifier.
        for i, approval in enumerate(gate.get("human_approvals", [])):
            approver = approval.get("approver")
            if isinstance(approver, dict) and (
                approver.get("id") in preparers
                or (isinstance(verifier, dict) and approver.get("id") == verifier.get("id"))
            ):
                errors.append(f"{gate_id}: human_approvals[{i}].approver is not independent")

    if errors:
        return 1, errors
    if blockers:
        return 2, blockers
    return 0, []
