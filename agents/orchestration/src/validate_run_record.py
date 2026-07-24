"""Draft 2020-12 and cross-field validation for lifecycle run records."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


GATE_IDS = tuple(f"G{index}" for index in range(1, 11))
SQS_BLOCKING_GATES = {"G3", "G4", "G5", "G7"}
REQUIRED_HUMAN_ROLES = {
    "G1": {"product owner"},
    "G2": {"product owner", "engineering lead"},
    "G3": {"system architect"},
    "G4": {"governance lead"},
    "G5": {"security lead"},
    "G6": {"engineering lead"},
    "G7": {"release owner"},
    "G8": {"release owner"},
    "G9": {"release authority"},
    "G10": {"service owner"},
}
REQUIRED_VERIFIER_ROLES = {
    "G4": {"compliance reviewer"},
    "G5": {"security reviewer"},
    "G6": {"test engineer"},
    "G7": {"compliance reviewer"},
}
REQUIRED_CONDITIONAL_AUTHORITIES = {
    "G4": {"data-control-owner"},
    "G5": {"human-key-owner"},
    "G6": {"uat-product-owner"},
    "G10": {"implicated-security-lead", "implicated-governance-lead"},
}
CANONICAL_CONDITIONAL_AUTHORITIES = {
    "data-control-owner": ("human-approver", "data/control owner"),
    "human-key-owner": ("human-approver", "human key owner"),
    "uat-product-owner": ("human-approver", "product owner"),
    "implicated-security-lead": ("human-approver", "security lead"),
    "implicated-governance-lead": ("human-approver", "governance lead"),
}
SQS_CATEGORY_IDS = {
    "platform-phase", "platform-component", "participant-digital-ecosystem-relevance",
    "digital-domain-impact", "governance-policy-impact", "trust-impact", "time-impact",
    "qkms-crypto-impact", "data-jurisdiction-impact", "meridian-impact",
    "ron-persistence-impact", "layer-0-impact", "evidence-requirement",
    "accreditation-relevance",
}
BOM_TYPES = {"SBOM", "CBOM", "QBOM", "AI-BOM", "Trust-BOM", "Time-BOM"}
DEFAULT_SCHEMA = Path(__file__).resolve().parents[1] / "run-record.schema.json"
LIFECYCLE_CONTRACT = Path(__file__).resolve().parents[3] / "plugins" / "agentic-sdlc" / "contracts" / "lifecycle-gates.json"


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _schema_errors(record: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Return complete Draft 2020-12 structural validation errors."""
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(record),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"schema {path}: {error.message}")
    return errors


def validation_errors(
    record: dict[str, Any], now: datetime | None = None, schema: dict[str, Any] | None = None,
    dispatch: dict[str, Any] | None = None,
) -> list[str]:
    """Return structural and cross-field lifecycle violations."""
    contract = schema or json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    errors = _schema_errors(record, contract)
    observed_at = now or datetime.now(timezone.utc)
    gates = record.get("lifecycle_gates", [])
    gate_ids = [gate.get("gate_id") for gate in gates]
    if gate_ids != list(GATE_IDS):
        errors.append("lifecycle_gates must contain each of G1 through G10 exactly once")
    contracts = {
        gate["id"]: gate
        for gate in json.loads(LIFECYCLE_CONTRACT.read_text(encoding="utf-8"))["gates"]
    }
    execution_gates = record.get("execution_summary", {}).get("gates", {})
    dispatch_required = {
        item.get("id") if isinstance(item, dict) else item
        for item in (dispatch or {}).get("required_quality_gates", [])
    }
    dispatch_required.update(
        item.get("gate_id")
        for item in (dispatch or {}).get("gate_dispatch", [])
        if item.get("status") == "required"
    )
    dispatch_ignored = set((dispatch or {}).get("ignored_quality_gates", []))
    dispatch_ignored.update(
        item.get("gate_id")
        for item in (dispatch or {}).get("gate_dispatch", [])
        if item.get("status") == "ignored"
    )
    for index, gate in enumerate(gates):
        gate_id = gate.get("gate_id")
        contract = contracts.get(gate_id, {})
        execution = execution_gates.get(gate_id)
        if execution is None:
            errors.append(f"{gate_id}: missing required execution record")
            continue
        expected_agents = list(dict.fromkeys(contract.get("author_agents", []) + contract.get("review_agents", ["code-reviewer"])))
        expected_artifacts = [
            {"agent_id": agent, "artifact_id": f"{gate_id.lower()}-{agent}-attestation"}
            for agent in expected_agents
        ]
        if execution.get("required_agents") != expected_agents:
            errors.append(f"{gate_id}: required agent set does not match lifecycle contract")
        if execution.get("required_tasks") != contract.get("tasks", []):
            errors.append(f"{gate_id}: required task set does not match lifecycle contract")
        if execution.get("required_agent_artifacts") != expected_artifacts:
            errors.append(f"{gate_id}: required agent artifacts do not match lifecycle contract")
        if execution.get("ignored") and not execution.get("ignore_reason"):
            errors.append(f"{gate_id}: ignored gate requires an explicit reason")
        if execution.get("ignored") and gate_id not in dispatch_ignored:
            errors.append(f"{gate_id}: ignore is not authorized by the project dispatch plan")
        if execution.get("configured") and dispatch is None:
            errors.append(f"{gate_id}: configured execution requires the project dispatch plan")
        if dispatch is not None and execution.get("configured") != (gate_id in dispatch_required or gate_id in dispatch_ignored):
            errors.append(f"{gate_id}: configured state does not match the project dispatch plan")
        if dispatch is not None and execution.get("ignored") != (gate_id in dispatch_ignored):
            errors.append(f"{gate_id}: ignore state does not match the project dispatch plan")
        if gate.get("status") in {"ready", "approved"} and execution.get("configured") and not execution.get("ignored"):
            if set(execution.get("dispatched_agents", [])) != set(expected_agents):
                errors.append(f"{gate_id}: advanced without dispatching every configured agent")
            if set(execution.get("completed_tasks", [])) != set(contract.get("tasks", [])):
                errors.append(f"{gate_id}: advanced without completing every configured task")
            produced = {
                (item.get("agent_id"), item.get("artifact_id"))
                for item in execution.get("produced_agent_artifacts", [])
                if item.get("revision") and item.get("digest")
            }
            required = {(item["agent_id"], item["artifact_id"]) for item in expected_artifacts}
            if not required.issubset(produced):
                errors.append(f"{gate_id}: advanced without immutable artifacts from every configured agent")
        if gate.get("status") in {"ready", "approved"} and execution.get("configured") and any(
            prior.get("status") not in {"approved", "invalidated"}
            and execution_gates.get(prior.get("gate_id"), {}).get("configured")
            and not execution_gates.get(prior.get("gate_id"), {}).get("ignored")
            for prior in gates[:index]
        ):
            errors.append(f"{gate_id}: violates lexical gate order")

    profile = record.get("sqs_impact_profile", {})
    category_ids = [item.get("id") for item in profile.get("impact_categories", [])]
    bom_types = [item.get("type") for item in profile.get("specialized_boms", [])]
    if len(category_ids) != 14 or set(category_ids) != SQS_CATEGORY_IDS:
        errors.append("SQS impact profile must contain each category exactly once")
    if len(bom_types) != 6 or set(bom_types) != BOM_TYPES:
        errors.append("SQS impact profile must contain each BOM type exactly once")
    unknown_profile_items = [
        item.get("id", item.get("type", "unknown-item"))
        for collection in ("impact_categories", "specialized_boms")
        for item in profile.get(collection, [])
        if item.get("applicability") == "unknown"
    ]
    if profile.get("status") == "complete" and (
        unknown_profile_items or profile.get("blocking_unknowns")
    ):
        errors.append("a complete SQS impact profile cannot contain unknowns or blockers")

    all_gates = [*gates, *record.get("specialist_attestations", [])]
    for gate in all_gates:
        gate_id = gate.get("gate_id", "unknown")
        lifecycle_gate = gate in gates
        status = gate.get("status")
        applicability = gate.get("applicability")
        preparer_ids = {item.get("id") for item in gate.get("preparers", [])}
        verifier = gate.get("independent_verifier")
        verifier_id = verifier.get("id") if isinstance(verifier, dict) else None
        verifier_role = str(verifier.get("role", "")).casefold() if isinstance(verifier, dict) else ""
        approvals = gate.get("human_approvals", [])
        approvers = [
            approval.get("approver")
            for approval in approvals
            if approval.get("status") == "approved" and isinstance(approval.get("approver"), dict)
        ]
        approver_ids = {approver.get("id") for approver in approvers}
        approver_roles = {str(approver.get("role", "")).casefold() for approver in approvers}

        if verifier_id and verifier_id in preparer_ids:
            errors.append(f"{gate_id}: verifier cannot be a preparer")
        if preparer_ids.intersection(approver_ids):
            errors.append(f"{gate_id}: approver cannot be a preparer")
        if verifier_id and verifier_id in approver_ids:
            errors.append(f"{gate_id}: verifier and approver must be different identities")
        if any(approver.get("kind") != "human" for approver in approvers):
            errors.append(f"{gate_id}: gate approvers must be human")
        declaration = gate.get("independence_declaration", {})
        if declaration.get("verifier_made_material_correction") is True:
            errors.append(f"{gate_id}: a material corrector cannot verify the same revision")

        authority_requirements = gate.get("authority_requirements", [])
        if lifecycle_gate:
            authority_ids = {item.get("authority_id") for item in authority_requirements}
            missing_authorities = REQUIRED_CONDITIONAL_AUTHORITIES.get(gate_id, set()) - authority_ids
            if missing_authorities:
                errors.append(
                    f"{gate_id}: missing conditional authority applicability for "
                    + ", ".join(sorted(missing_authorities))
                )
        for requirement in authority_requirements:
            authority_id = requirement.get("authority_id", "unknown-authority")
            canonical = CANONICAL_CONDITIONAL_AUTHORITIES.get(authority_id)
            if canonical:
                expected_type, expected_role = canonical
                actual_type = requirement.get("authority_type")
                actual_role = str(requirement.get("role", "")).casefold()
                if actual_type != expected_type or actual_role != expected_role:
                    errors.append(
                        f"{gate_id}: {authority_id} must use canonical authority type "
                        f"{expected_type} and role {expected_role}"
                    )
            if requirement.get("applicability") == "not-applicable" and not requirement.get("rationale"):
                errors.append(f"{gate_id}: {authority_id} not-applicable requires a rationale")

        if applicability == "not-applicable" and not gate.get("applicability_rationale"):
            errors.append(f"{gate_id}: not-applicable requires a rationale")
        if status == "approved":
            if applicability != "applicable":
                errors.append(f"{gate_id}: only an applicable gate may be approved")
            if not gate.get("evidence_refs"):
                errors.append(f"{gate_id}: approved gate requires evidence")
            if not verifier_id or declaration.get("verifier_confirmed_not_preparer") is not True:
                errors.append(f"{gate_id}: approved gate requires an independent verifier")
            if lifecycle_gate:
                required_roles = REQUIRED_HUMAN_ROLES.get(gate_id, set())
                if not required_roles.issubset(approver_roles):
                    errors.append(
                        f"{gate_id}: approved gate requires human authority roles "
                        + ", ".join(sorted(required_roles))
                    )
                required_verifier_roles = REQUIRED_VERIFIER_ROLES.get(gate_id, set())
                if required_verifier_roles and verifier_role not in required_verifier_roles:
                    errors.append(
                        f"{gate_id}: approved gate requires independent verifier role "
                        + " or ".join(sorted(required_verifier_roles))
                    )

                for requirement in authority_requirements:
                    authority_id = requirement.get("authority_id", "unknown-authority")
                    authority_applicability = requirement.get("applicability")
                    authority_role = str(requirement.get("role", "")).casefold()
                    authority_type = requirement.get("authority_type")
                    if authority_applicability == "unknown":
                        errors.append(f"{gate_id}: unknown authority applicability blocks approval")
                    if authority_applicability != "applicable":
                        continue
                    if authority_type == "independent-verifier" and verifier_role != authority_role:
                        errors.append(f"{gate_id}: required verifier authority {authority_role} is unsatisfied")
                    if authority_type == "human-approver" and authority_role not in approver_roles:
                        errors.append(f"{gate_id}: required human authority {authority_role} is unsatisfied")
            if (
                unknown_profile_items
                or profile.get("blocking_unknowns")
                or profile.get("status") == "blocked"
            ) and gate_id in SQS_BLOCKING_GATES:
                errors.append(f"{gate_id}: unknown SQS applicability blocks approval")

            exceptions_by_finding = {
                exception.get("finding_id") for exception in gate.get("exceptions", [])
            }
            for finding in gate.get("findings", []):
                if finding.get("severity") not in {"critical", "high"}:
                    continue
                if finding.get("status") == "resolved":
                    continue
                if (
                    finding.get("status") != "accepted-exception"
                    or finding.get("finding_id") not in exceptions_by_finding
                ):
                    errors.append(f"{gate_id}: unresolved critical/high finding blocks approval")

        finding_ids = {finding.get("finding_id") for finding in gate.get("findings", [])}
        required_exception_fields = {
            "exception_id", "finding_id", "justification", "compensating_controls",
            "owner", "approver", "expires_at", "remediation_plan",
        }
        for exception in gate.get("exceptions", []):
            missing_exception = sorted(required_exception_fields - set(exception))
            if missing_exception:
                errors.append(
                    f"{gate_id}: incomplete exception: " + ", ".join(missing_exception)
                )
            if exception.get("finding_id") not in finding_ids:
                errors.append(f"{gate_id}: exception must reference a gate finding")
            for identity_field in ("owner", "approver"):
                identity = exception.get(identity_field)
                if not isinstance(identity, dict) or identity.get("kind") != "human":
                    errors.append(f"{gate_id}: exception {identity_field} must be human")
            try:
                expires_at = _parse_datetime(exception["expires_at"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{gate_id}: exception expiry must be a valid timezone-aware timestamp")
                continue
            if expires_at <= observed_at:
                errors.append(f"{gate_id}: expired exception cannot support progression")

    gate_by_id = {gate.get("gate_id"): gate for gate in gates}
    for index, gate_id in enumerate(GATE_IDS):
        gate = gate_by_id.get(gate_id, {})
        if gate.get("status") != "approved":
            continue
        for prerequisite_id in GATE_IDS[:index]:
            prerequisite = gate_by_id.get(prerequisite_id, {})
            satisfied = (
                prerequisite.get("status") == "approved"
                or prerequisite.get("applicability") == "not-applicable"
            )
            if not satisfied:
                errors.append(f"{gate_id}: prerequisite {prerequisite_id} is not satisfied")

    for invalidation in record.get("re_entry_history", []):
        earliest = invalidation.get("earliest_gate")
        invalidated = invalidation.get("invalidated_gate_ids", [])
        if earliest in GATE_IDS:
            expected = set(GATE_IDS[GATE_IDS.index(earliest) :])
            if not expected.issubset(invalidated):
                errors.append(f"{earliest}: invalidation must include every downstream gate")

    return errors


def validate_run_record(
    record: dict[str, Any], now: datetime | None = None, schema: dict[str, Any] | None = None,
    dispatch: dict[str, Any] | None = None,
) -> None:
    """Raise ValueError when a run record violates the lifecycle contract."""
    errors = validation_errors(record, now, schema, dispatch)
    if errors:
        raise ValueError("Invalid lifecycle run record: " + "; ".join(errors))


def _load_record(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is required to validate YAML run records") from error
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an authoritative lifecycle run record")
    parser.add_argument("record", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--dispatch-plan", type=Path)
    arguments = parser.parse_args()
    record = _load_record(arguments.record)
    schema = json.loads(arguments.schema.read_text(encoding="utf-8"))
    dispatch = (
        json.loads(arguments.dispatch_plan.read_text(encoding="utf-8"))
        if arguments.dispatch_plan
        else None
    )
    validate_run_record(record, schema=schema, dispatch=dispatch)
    print(f"valid: {arguments.record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
