"""Cross-field lifecycle run-record validation tests."""

from __future__ import annotations

import json
import sys
import subprocess
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from validate_run_record import BOM_TYPES, SQS_CATEGORY_IDS, validate_run_record  # noqa: E402


def _identity(identifier: str, kind: str = "human") -> dict[str, str]:
    return {"id": identifier, "role": identifier, "kind": kind}


def _evidence(identifier: str = "E-1") -> dict[str, str]:
    return {
        "evidence_id": identifier,
        "uri": f"repo://evidence/{identifier}",
        "hash_algorithm": "sha256",
        "hash": "a" * 64,
        "classification": "internal",
    }


def _authority(
    authority_id: str,
    role: str,
    applicability: str = "not-applicable",
) -> dict[str, str]:
    return {
        "authority_id": authority_id,
        "authority_type": "human-approver",
        "role": role,
        "applicability": applicability,
        "rationale": "not implicated" if applicability == "not-applicable" else "required",
    }


def _record() -> dict:
    verifier_roles = {
        4: "Compliance Reviewer",
        5: "Security Reviewer",
        6: "Test Engineer",
        7: "Compliance Reviewer",
    }
    conditional_authorities = {
        4: [_authority("data-control-owner", "Data/Control Owner")],
        5: [_authority("human-key-owner", "Human Key Owner")],
        6: [_authority("uat-product-owner", "Product Owner")],
        10: [
            _authority("implicated-security-lead", "Security Lead"),
            _authority("implicated-governance-lead", "Governance Lead"),
        ],
    }
    gates = []
    for index in range(1, 11):
        gates.append(
            {
                "tier": "lifecycle",
                "gate_id": f"G{index}",
                "name": f"Gate {index}",
                "applicability": "applicable",
                "applicability_rationale": "required",
                "status": "ready",
                "artifact_bindings": [],
                "preparers": [_identity(f"author-{index}", "agent")],
                "independent_verifier": {
                    "id": f"reviewer-{index}",
                    "role": verifier_roles.get(index, f"Reviewer {index}"),
                    "kind": "agent",
                },
                "independence_declaration": {
                    "verifier_confirmed_not_preparer": True,
                    "verifier_made_material_correction": False,
                },
                "authority_requirements": conditional_authorities.get(index, []),
                "human_approvals": [],
                "decided_at": None,
                "evidence_refs": [],
                "knowledge_status": "unavailable",
                "findings": [],
                "exceptions": [],
                "invalidation_history": [],
                "required_reentry_gate": None,
            }
        )
    impact_categories = [
        {
            "id": identifier,
            "applicability": "unknown",
            "definition_reference": None,
            "rationale": None,
            "owner": None,
            "evidence_refs": [],
        }
        for identifier in sorted(SQS_CATEGORY_IDS)
    ]
    specialized_boms = [
        {
            "type": bom_type,
            "applicability": "unknown",
            "definition_reference": None,
            "owner": None,
            "evidence_refs": [],
        }
        for bom_type in sorted(BOM_TYPES)
    ]
    execution_gates = {}
    lifecycle_contract = json.loads(
        (ROOT.parent.parent / "plugins" / "agentic-sdlc" / "contracts" / "lifecycle-gates.json").read_text(
            encoding="utf-8"
        )
    )["gates"]
    for contract in lifecycle_contract:
        gate_id = contract["id"]
        agents = list(dict.fromkeys(
            contract.get("author_agents", []) + contract.get("review_agents", ["code-reviewer"])
        ))
        execution_gates[gate_id] = {
            "configured": False,
            "ignored": False,
            "ignore_reason": None,
            "required_agents": agents,
            "dispatched_agents": [],
            "required_tasks": contract["tasks"],
            "completed_tasks": [],
            "required_agent_artifacts": [
                {"agent_id": agent, "artifact_id": f"{gate_id.lower()}-{agent}-attestation"}
                for agent in agents
            ],
            "produced_agent_artifacts": [],
        }
    return {
        "version": 2,
        "task_id": "TEST-1",
        "recorded_at": "2026-07-21T00:00:00Z",
        "classification": "internal",
        "mode": "planning-review-only",
        "baseline_revision": "abc123",
        "scope": "unit test",
        "disposition": "testing",
        "intent_record_id": None,
        "requirements_baseline_id": None,
        "current_lifecycle_phase": "intent",
        "knowledge_retrieval": {
            "status": "unavailable",
            "reason": "test configuration absent",
            "query_ids": [],
            "evidence_refs": [],
            "influence": "none",
        },
        "lifecycle_gates": gates,
        "sqs_impact_profile": {
            "profile_id": "PROFILE-1",
            "status": "blocked",
            "impact_categories": impact_categories,
            "specialized_boms": specialized_boms,
            "blocking_unknowns": ["definition missing"],
        },
        "specialist_attestations": [],
        "re_entry_history": [],
        "execution_summary": {"gates": execution_gates},
    }


class RunRecordValidationTests(unittest.TestCase):
    def _run_cli(self, record: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run-record.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(ROOT / "src" / "validate_run_record.py"), str(path)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

    def test_sample_run_record_validates_through_cli(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "src" / "validate_run_record.py"),
                str(ROOT / "runs" / "SAMPLE-001-IMPLEMENT" / "run-record.yaml"),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_non_approved_fail_closed_record(self) -> None:
        validate_run_record(_record())

    def test_rejects_invalid_recorded_at_type(self) -> None:
        record = _record()
        record["recorded_at"] = 123
        with self.assertRaisesRegex(ValueError, "schema recorded_at"):
            validate_run_record(record)

    def test_rejects_invalid_lifecycle_phase_enum(self) -> None:
        record = _record()
        record["current_lifecycle_phase"] = "bogus"
        with self.assertRaisesRegex(ValueError, "schema current_lifecycle_phase"):
            validate_run_record(record)

    def test_rejects_unexpected_top_level_property(self) -> None:
        record = _record()
        record["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "Additional properties are not allowed"):
            validate_run_record(record)

    def test_rejects_malformed_nested_evidence(self) -> None:
        record = _record()
        record["lifecycle_gates"][0]["evidence_refs"] = [{"evidence_id": "E-1"}]
        with self.assertRaisesRegex(ValueError, "schema lifecycle_gates.0.evidence_refs.0"):
            validate_run_record(record)

    def test_cli_rejects_structural_schema_violations(self) -> None:
        cases = []
        invalid_type = _record()
        invalid_type["recorded_at"] = 123
        cases.append(("type", invalid_type, "schema recorded_at"))
        invalid_enum = _record()
        invalid_enum["current_lifecycle_phase"] = "bogus"
        cases.append(("enum", invalid_enum, "schema current_lifecycle_phase"))
        additional_property = _record()
        additional_property["unexpected"] = True
        cases.append(("additional", additional_property, "Additional properties are not allowed"))
        malformed_nested = _record()
        malformed_nested["lifecycle_gates"][0]["evidence_refs"] = [{"evidence_id": "E-1"}]
        cases.append(("nested", malformed_nested, "schema lifecycle_gates.0.evidence_refs.0"))

        for name, record, expected in cases:
            with self.subTest(case=name):
                result = self._run_cli(record)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)

    def test_rejects_missing_gate(self) -> None:
        record = _record()
        record["lifecycle_gates"].pop()
        with self.assertRaisesRegex(ValueError, "each of G1 through G10"):
            validate_run_record(record)

    def test_rejects_self_approval(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][0]
        gate["human_approvals"] = [{
            "status": "approved", "approver": deepcopy(gate["preparers"][0])
        }]
        with self.assertRaisesRegex(ValueError, "approver cannot be a preparer"):
            validate_run_record(record)

    def test_rejects_approved_gate_with_unknown_sqs_applicability(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][3]
        gate["status"] = "approved"
        gate["evidence_refs"] = [{"evidence_id": "E-1"}]
        gate["human_approvals"] = [
            {"status": "approved", "approver": {"id": "gov", "role": "Governance Lead", "kind": "human"}},
            {"status": "approved", "approver": {"id": "data", "role": "Data/Control Owner", "kind": "human"}},
        ]
        with self.assertRaisesRegex(ValueError, "unknown SQS applicability blocks approval"):
            validate_run_record(record)

    def test_rejects_expired_exception(self) -> None:
        record = _record()
        record["lifecycle_gates"][4]["exceptions"] = [
            {"expires_at": "2026-01-01T00:00:00Z"}
        ]
        with self.assertRaisesRegex(ValueError, "expired exception"):
            validate_run_record(
                record,
                now=datetime(2026, 7, 21, tzinfo=timezone.utc),
            )

    def test_rejects_incomplete_exception(self) -> None:
        record = _record()
        record["lifecycle_gates"][4]["exceptions"] = [
            {"expires_at": "2027-01-01T00:00:00Z"}
        ]
        with self.assertRaisesRegex(ValueError, "incomplete exception"):
            validate_run_record(
                record,
                now=datetime(2026, 7, 21, tzinfo=timezone.utc),
            )

    def test_rejects_incomplete_downstream_invalidation(self) -> None:
        record = _record()
        record["re_entry_history"] = [
            {"earliest_gate": "G6", "invalidated_gate_ids": ["G6", "G7"]}
        ]
        with self.assertRaisesRegex(ValueError, "every downstream gate"):
            validate_run_record(record)

    def test_rejects_explicit_sqs_blocker_without_unknown_items(self) -> None:
        record = _record()
        profile = record["sqs_impact_profile"]
        profile["impact_categories"] = [
            {"id": identifier, "applicability": "not-applicable"}
            for identifier in sorted(SQS_CATEGORY_IDS)
        ]
        profile["specialized_boms"] = [
            {"type": bom_type, "applicability": "not-applicable"}
            for bom_type in sorted(BOM_TYPES)
        ]
        gate = record["lifecycle_gates"][3]
        gate["status"] = "approved"
        gate["evidence_refs"] = [{"evidence_id": "E-1"}]
        gate["human_approvals"] = [
            {"status": "approved", "approver": {"id": "gov", "role": "Governance Lead", "kind": "human"}},
            {"status": "approved", "approver": {"id": "data", "role": "Data/Control Owner", "kind": "human"}},
        ]
        with self.assertRaisesRegex(ValueError, "unknown SQS applicability blocks approval"):
            validate_run_record(record)

    def test_rejects_unresolved_high_finding_on_approved_gate(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][0]
        gate["status"] = "approved"
        gate["evidence_refs"] = [{"evidence_id": "E-1"}]
        gate["human_approvals"] = [
            {"status": "approved", "approver": _identity("product-owner") | {"role": "Product Owner"}}
        ]
        gate["findings"] = [
            {"finding_id": "F-1", "severity": "high", "status": "open"}
        ]
        with self.assertRaisesRegex(ValueError, "unresolved critical/high finding"):
            validate_run_record(record)

    def test_rejects_approved_gate_without_evidence(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][0]
        gate["status"] = "approved"
        gate["human_approvals"] = [
            {"status": "approved", "approver": _identity("product-owner") | {"role": "Product Owner"}}
        ]
        with self.assertRaisesRegex(ValueError, "approved gate requires evidence"):
            validate_run_record(record)

    def test_rejects_accepted_finding_without_linked_exception(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][0]
        gate["status"] = "approved"
        gate["evidence_refs"] = [{"evidence_id": "E-1"}]
        gate["human_approvals"] = [
            {"status": "approved", "approver": _identity("product-owner") | {"role": "Product Owner"}}
        ]
        gate["findings"] = [
            {"finding_id": "F-1", "severity": "critical", "status": "accepted-exception"}
        ]
        with self.assertRaisesRegex(ValueError, "unresolved critical/high finding"):
            validate_run_record(record)

    def test_rejects_downstream_approval_without_prerequisites(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][9]
        gate["status"] = "approved"
        gate["evidence_refs"] = [{"evidence_id": "E-1"}]
        gate["human_approvals"] = [
            {"status": "approved", "approver": _identity("service-owner") | {"role": "Service Owner"}}
        ]
        with self.assertRaisesRegex(ValueError, "prerequisite G1 is not satisfied"):
            validate_run_record(record)

    def test_rejects_verifier_as_approver(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][0]
        gate["human_approvals"] = [
            {"status": "approved", "approver": deepcopy(gate["independent_verifier"]) | {"role": "Product Owner", "kind": "human"}}
        ]
        with self.assertRaisesRegex(ValueError, "verifier and approver must be different"):
            validate_run_record(record)

    def test_rejects_agent_as_gate_approver(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][0]
        gate["human_approvals"] = [
            {"status": "approved", "approver": {"id": "agent-po", "role": "Product Owner", "kind": "agent"}}
        ]
        with self.assertRaisesRegex(ValueError, "gate approvers must be human"):
            validate_run_record(record)

    def test_g2_requires_both_product_and_engineering_authorities(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][1]
        gate["status"] = "approved"
        gate["evidence_refs"] = [{"evidence_id": "E-1"}]
        gate["human_approvals"] = [
            {"status": "approved", "approver": {"id": "po", "role": "Product Owner", "kind": "human"}}
        ]
        with self.assertRaisesRegex(ValueError, "engineering lead"):
            validate_run_record(record)

    def test_g5_requires_security_reviewer(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][4]
        gate["status"] = "approved"
        gate["evidence_refs"] = [_evidence()]
        gate["independent_verifier"]["role"] = "Debugging Engineer"
        gate["human_approvals"] = [
            {"status": "approved", "approver": {"id": "security", "role": "Security Lead", "kind": "human"}}
        ]
        with self.assertRaisesRegex(ValueError, "independent verifier role security reviewer"):
            validate_run_record(record)

    def test_gate_specific_independent_reviewer_roles(self) -> None:
        cases = (
            (3, "Governance Lead", "compliance reviewer"),
            (5, "Engineering Lead", "test engineer"),
            (6, "Release Owner", "compliance reviewer"),
        )
        for gate_index, approver_role, expected_reviewer in cases:
            with self.subTest(gate=f"G{gate_index + 1}"):
                record = _record()
                gate = record["lifecycle_gates"][gate_index]
                gate["status"] = "approved"
                gate["evidence_refs"] = [_evidence()]
                gate["independent_verifier"]["role"] = "Debugging Engineer"
                gate["human_approvals"] = [
                    {
                        "status": "approved",
                        "approver": {"id": "authority", "role": approver_role, "kind": "human"},
                    }
                ]
                with self.assertRaisesRegex(
                    ValueError,
                    f"independent verifier role {expected_reviewer}",
                ):
                    validate_run_record(record)

    def test_approved_gate_requires_conditional_authority_applicability(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][4]
        gate["status"] = "approved"
        gate["evidence_refs"] = [_evidence()]
        gate["authority_requirements"] = []
        gate["human_approvals"] = [
            {"status": "approved", "approver": {"id": "security", "role": "Security Lead", "kind": "human"}}
        ]
        with self.assertRaisesRegex(ValueError, "missing conditional authority applicability for human-key-owner"):
            validate_run_record(record)

    def test_applicable_conditional_authority_requires_matching_approver(self) -> None:
        record = _record()
        gate = record["lifecycle_gates"][4]
        gate["status"] = "approved"
        gate["evidence_refs"] = [_evidence()]
        gate["authority_requirements"] = [
            _authority("human-key-owner", "Human Key Owner", "applicable")
        ]
        gate["human_approvals"] = [
            {"status": "approved", "approver": {"id": "security", "role": "Security Lead", "kind": "human"}}
        ]
        with self.assertRaisesRegex(ValueError, "required human authority human key owner is unsatisfied"):
            validate_run_record(record)

    def test_conditional_authority_ids_reject_role_and_type_relabeling(self) -> None:
        cases = (
            (3, "data-control-owner"),
            (4, "human-key-owner"),
            (5, "uat-product-owner"),
            (9, "implicated-security-lead"),
            (9, "implicated-governance-lead"),
        )
        for gate_index, authority_id in cases:
            for field, altered_value in (
                ("role", "Relabeled Authority"),
                ("authority_type", "independent-verifier"),
            ):
                with self.subTest(gate=f"G{gate_index + 1}", authority=authority_id, field=field):
                    record = _record()
                    requirement = next(
                        item
                        for item in record["lifecycle_gates"][gate_index]["authority_requirements"]
                        if item["authority_id"] == authority_id
                    )
                    requirement[field] = altered_value
                    with self.assertRaisesRegex(
                        ValueError,
                        f"{authority_id} must use canonical authority type",
                    ):
                        validate_run_record(record)

    def test_rejects_specialist_self_verification_and_expired_exception(self) -> None:
        record = _record()
        specialist = deepcopy(record["lifecycle_gates"][0])
        specialist["gate_id"] = "threat-model"
        specialist["tier"] = "specialist"
        specialist["independent_verifier"] = deepcopy(specialist["preparers"][0])
        specialist["exceptions"] = [{"expires_at": "2025-01-01T00:00:00Z"}]
        record["specialist_attestations"] = [specialist]
        with self.assertRaisesRegex(ValueError, "verifier cannot be a preparer"):
            validate_run_record(record, now=datetime(2026, 7, 21, tzinfo=timezone.utc))

    def test_rejects_duplicate_sqs_categories(self) -> None:
        record = _record()
        record["sqs_impact_profile"]["impact_categories"][0]["id"] = record["sqs_impact_profile"]["impact_categories"][1]["id"]
        with self.assertRaisesRegex(ValueError, "each category exactly once"):
            validate_run_record(record)


if __name__ == "__main__":
    unittest.main()
