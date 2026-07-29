"""Regression tests for the Python selector and its lifecycle contract inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

import agentic_sdlc_contracts  # noqa: E402
from build_dispatch_plan import build_dispatch_plan  # noqa: E402
from routing import glob_to_regex, load_catalog, load_routing  # noqa: E402
from select_agents import (  # noqa: E402
    _origin_slug,
    discover_changed_files,
    explicit_files,
    resolve_knowledge_source,
)

CONFIG = load_routing(ROOT / "routing.yaml")
CATALOG = load_catalog(AGENTS_ROOT / "catalog.yaml")
AGENTIC_SDLC_AVAILABLE = bool(os.environ.get("AGENTIC_SDLC_BIN") or shutil.which("agentic-sdlc"))


def catalog_definitions() -> dict[str, str]:
    definitions: dict[str, str] = {}
    current_agent: str | None = None
    for line in (AGENTS_ROOT / "catalog.yaml").read_text(encoding="utf-8").splitlines():
        agent_match = line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":")
        if agent_match:
            current_agent = line.strip()[:-1]
        elif current_agent and line.strip().startswith("definition:"):
            definitions[current_agent] = line.split(":", 1)[1].strip()
    return definitions


def plan(**overrides: object) -> dict[str, object]:
    values = {
        "task": "Change the application",
        "changed_files": [],
        "changed_file_source": "test",
        "repository_root": str(AGENTS_ROOT.parent),
        "source": "example/repository",
        **overrides,
    }
    return build_dispatch_plan(CONFIG, CATALOG, values)


class SelectorTests(unittest.TestCase):
    @staticmethod
    def quality_gate_ids(result: dict[str, object]) -> list[str]:
        return [gate["id"] for gate in result["required_quality_gates"]]

    def test_catalog_definition_paths_exist(self) -> None:
        definitions = catalog_definitions()
        self.assertEqual(set(CATALOG), set(definitions))
        for agent, relative_path in definitions.items():
            with self.subTest(agent=agent):
                self.assertTrue((AGENTS_ROOT / relative_path).is_file(), relative_path)

    def test_glob_matching_supports_root_and_nested_paths(self) -> None:
        self.assertIsNotNone(glob_to_regex("**/*.go").search("main.go"))
        self.assertIsNotNone(glob_to_regex("**/*.go").search("services/api/main.go"))
        self.assertIsNotNone(glob_to_regex("terraform/**").search("terraform/modules/vm/main.tf"))
        self.assertIsNotNone(glob_to_regex(".gitlab-ci.yml").search(".gitlab-ci.yml"))
        self.assertIsNone(glob_to_regex("**/*.go").search("main.ts"))

    def test_plugin_packaging_routes_to_agent_suite_governance(self) -> None:
        result = plan(
            task="Package the Secure Cloud Agentic SDLC provider",
            changed_files=[
                "plugins/cadre/provider.json",
                ".agents/plugins/marketplace.json",
            ],
            classification="internal",
            task_id="PLUGIN-1",
        )
        self.assertEqual(result["workflow"], "debugging")
        self.assertIn("application-engineer", result["agents"]["primary"])
        self.assertIn("debugging-engineer", result["agents"]["primary"])
        self.assertIn("test-engineer", result["agents"]["reviewers"])

    def test_selects_frontend_and_backend_with_cross_stack_coordination(self) -> None:
        result = plan(
            task="Add a React upload form backed by a PostgreSQL API",
            changed_files=["frontend/src/Upload.tsx", "services/upload/main.go"],
            classification="internal",
            task_id="APP-42",
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["workflow"], "new-service")
        self.assertEqual(result["agents"]["primary"], ["frontend-engineer", "backend-engineer"])
        self.assertIn("test-engineer", result["agents"]["reviewers"])
        self.assertIn("code-reviewer", result["agents"]["reviewers"])
        self.assertIn("application-engineer", result["agents"]["support"])
        self.assertEqual(result["knowledge_context"]["status"], "planned")
        requests = result["knowledge_context"]["requests"]
        self.assertTrue(any(request["agent"] == "frontend-engineer" for request in requests))
        self.assertTrue(all("APP-42" in request["invocation"]["args"] for request in requests))
        self.assertTrue(all("\n" not in request["query"] and "\r" not in request["query"] for request in requests))
        expected_launcher = {
            "runtime": "python",
            "minimum_version": "3.10",
            "resolution": "runner-probed",
        }
        self.assertTrue(all(request["invocation"]["launcher"] == expected_launcher for request in requests))
        self.assertTrue(all(Path(request["invocation"]["args"][0]).is_absolute() for request in requests))
        self.assertTrue(all(request["invocation"]["args"][1] == "context" for request in requests))

    def test_two_route_task_forms_cross_stack_build_team_only(self) -> None:
        result = plan(
            task="Add a React upload form backed by a PostgreSQL API",
            changed_files=["frontend/src/Upload.tsx", "services/upload/main.go"],
            classification="internal",
            task_id="APP-42",
        )
        team_ids = [team["id"] for team in result["teams"]]
        self.assertEqual(team_ids, ["cross-stack-build"])
        team = result["teams"][0]
        self.assertEqual(team["type"], "fixed")
        self.assertEqual(set(team["members"]), {"frontend-engineer", "backend-engineer"})
        self.assertEqual(team["communication_mode"], "peer")
        self.assertEqual(team["fallback"], "orchestrator-relayed")

    def test_three_stack_task_also_forms_parallel_review_team(self) -> None:
        result = plan(
            task="Add a React upload form backed by a PostgreSQL API with Terraform infra",
            changed_files=["frontend/src/Upload.tsx", "services/upload/main.go", "terraform/main.tf"],
            classification="internal",
            task_id="APP-43",
        )
        team_ids = {team["id"] for team in result["teams"]}
        self.assertEqual(team_ids, {"cross-stack-build", "parallel-review"})
        review_team = next(team for team in result["teams"] if team["id"] == "parallel-review")
        self.assertEqual(set(review_team["members"]), {"code-reviewer", "infrastructure-reviewer"})

    def test_intermittent_debugging_task_forms_dynamic_team(self) -> None:
        result = plan(
            task="Debug an intermittent panic that has not converged after several fixes",
            changed_files=["services/internal/repository/regression/panic_test.go"],
            classification="internal",
            task_id="DBG-TEAM-1",
        )
        team = next(team for team in result["teams"] if team["id"] == "competing-hypotheses-debugging")
        self.assertEqual(team["type"], "dynamic")
        self.assertEqual(team["role"], "debugging-engineer")
        self.assertEqual(team["instances"], {"min": 2, "max": 4})
        self.assertIn("intermittent", team["trigger_reason"]["keywords"])

    def test_ordinary_debugging_task_does_not_form_dynamic_team(self) -> None:
        result = plan(
            task="Debug a panic and identify the root cause from the stack trace",
            changed_files=["services/internal/repository/regression/panic_test.go"],
            classification="internal",
            task_id="DBG-1",
        )
        self.assertNotIn("competing-hypotheses-debugging", [team["id"] for team in result["teams"]])

    def test_single_route_task_has_no_teams(self) -> None:
        result = plan(task="Update Terraform", changed_files=["main.tf"])
        self.assertEqual(result["teams"], [])

    def test_team_members_are_always_a_subset_of_selected_agents(self) -> None:
        cases = [
            (
                "Add a React upload form backed by a PostgreSQL API with Terraform infra",
                ["frontend/src/Upload.tsx", "services/upload/main.go", "terraform/main.tf"],
            ),
            (
                "Review dependency SBOM and container image provenance for the pipeline and infra change",
                ["services/go.mod", ".gitlab-ci.yml", "terraform/main.tf"],
            ),
        ]
        for task, changed_files in cases:
            with self.subTest(task=task):
                result = plan(task=task, changed_files=changed_files)
                selected = {*result["agents"]["primary"], *result["agents"]["reviewers"], *result["agents"]["support"]}
                for team in result["teams"]:
                    if team["type"] == "fixed":
                        self.assertTrue(set(team["members"]).issubset(selected))
                    else:
                        self.assertIn(team["role"], selected)

    def test_knowledge_invocation_uses_resolved_repository_source(self) -> None:
        from build_dispatch_plan import KNOWLEDGE_STORE_ROOT

        result = plan(
            task="Add a React upload form backed by a PostgreSQL API",
            changed_files=["frontend/src/Upload.tsx"],
            classification="internal",
            task_id="NO-SOURCE-1",
        )
        requests = result["knowledge_context"]["requests"]
        self.assertTrue(requests)
        for request in requests:
            args = request["invocation"]["args"]
            self.assertIn("--source", args)
            self.assertEqual("example/repository", args[args.index("--source") + 1])
            self.assertEqual(str(KNOWLEDGE_STORE_ROOT / "src" / "cli.py"), args[0])
            self.assertNotIn("--config", args)
            self.assertNotIn("cwd", request["invocation"])

    @unittest.skipUnless(AGENTIC_SDLC_AVAILABLE, "Agentic SDLC executable is required")
    def test_emits_schema_v2_quality_gates_separately_from_human_gates(self) -> None:
        result = plan(
            task="Deploy to production with Terraform",
            changed_files=["terraform/service/main.tf"],
        )
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["workflow"], "production-release")
        self.assertEqual(self.quality_gate_ids(result), ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"])
        production_gate = next(
            gate for gate in result["required_quality_gates"] if gate["id"] == "G9"
        )
        self.assertEqual(production_gate["contributing_routes"], ["production"])
        self.assertEqual([gate["id"] for gate in result["human_gates"]], ["production-change"])

    def test_dispatch_disposition_is_staffed_when_a_primary_or_reviewer_is_selected(self) -> None:
        result = plan(
            task="Deploy to production with Terraform",
            changed_files=["terraform/service/main.tf"],
        )
        self.assertEqual(result["dispatch_disposition"]["status"], "staffed")

    def test_dispatch_disposition_is_no_agents_selected_when_nothing_matches(self) -> None:
        result = plan(task="", changed_files=[])
        self.assertEqual(result["status"], "needs-triage")
        self.assertEqual(result["dispatch_disposition"], {
            "status": "no-agents-selected",
            "reason": "No route or risk rule matched this task; there is nothing to dispatch.",
        })

    def test_dispatch_disposition_flags_advisory_only_destructive_but_reviewable_workflow(self) -> None:
        # Regression for issue #45: exporting a local backlog artifact and then
        # deleting the source GitLab issues only ever matched change_intake's
        # generic "delete" keyword, which lands product-intent-agent,
        # requirements-agent, and code-reviewer in `support` with no primary
        # or reviewer role selected. Without an explicit disposition field,
        # that support-only selection was indistinguishable in the plan from a
        # fully-staffed one, so an orchestrator could silently perform the
        # destructive step itself with no structured reason surfaced.
        result = plan(
            task="Export the GitLab issues to a local backlog artifact, then delete the GitLab issues",
            changed_files=[],
        )
        self.assertEqual(result["agents"]["primary"], [])
        self.assertEqual(result["agents"]["reviewers"], [])
        self.assertTrue(result["agents"]["support"])
        self.assertEqual(result["dispatch_disposition"]["status"], "advisory-only")
        for agent in result["agents"]["support"]:
            self.assertIn(agent, result["dispatch_disposition"]["reason"])

    @unittest.skipUnless(AGENTIC_SDLC_AVAILABLE, "Agentic SDLC executable is required")
    def test_selects_product_intake_agents_and_gates_for_intent_only(self) -> None:
        result = plan(task="Capture product intent and requirements decomposition", changed_files=[])
        self.assertEqual(result["workflow"], "product-intake")
        self.assertIn("product-intent-agent", result["agents"]["primary"])
        self.assertIn("requirements-agent", result["agents"]["primary"])
        self.assertEqual(self.quality_gate_ids(result), ["G1", "G2"])

    @unittest.skipUnless(AGENTIC_SDLC_AVAILABLE, "Agentic SDLC executable is required")
    def test_change_work_always_adds_intent_and_requirements_gates(self) -> None:
        result = plan(task="Implement a GitHub approval integration", changed_files=[])
        self.assertEqual(self.quality_gate_ids(result), ["G1", "G2"])
        self.assertIn("product-intent-agent", result["agents"]["support"])
        self.assertIn("requirements-agent", result["agents"]["support"])

    @unittest.skipUnless(AGENTIC_SDLC_AVAILABLE, "Agentic SDLC executable is required")
    def test_combined_product_intent_and_architecture_uses_new_service(self) -> None:
        result = plan(task="Capture product intent and define the service architecture", changed_files=[])
        self.assertEqual(result["workflow"], "new-service")
        self.assertIn("product-intent-agent", result["agents"]["primary"])
        self.assertIn("cloud-architect", result["agents"]["support"])
        self.assertEqual(self.quality_gate_ids(result), ["G1", "G2", "G3"])

    def test_selects_governance_data_and_crypto_specialists_narrowly(self) -> None:
        governance = plan(task="Assess governance impact and prepare an accreditation plan", changed_files=[])
        data = plan(task="Define non-egress and data residency controls", changed_files=[])
        crypto = plan(task="Assess PQC crypto agility and downgrade risk", changed_files=[])

        self.assertIn("governance-planner", governance["agents"]["primary"])
        self.assertIn("compliance-reviewer", governance["agents"]["reviewers"])
        self.assertIn("data-governance-engineer", data["agents"]["primary"])
        self.assertIn("security-reviewer", data["agents"]["reviewers"])
        self.assertIn("compliance-reviewer", data["agents"]["reviewers"])
        self.assertIn("cryptographic-assurance-engineer", crypto["agents"]["primary"])
        self.assertIn("security-reviewer", crypto["agents"]["reviewers"])
        self.assertIn("threat-modeler", crypto["agents"]["support"])
        self.assertTrue(
            set(crypto["agents"]["primary"]).isdisjoint(crypto["agents"]["reviewers"])
        )

    def test_selects_authority_aides_narrowly_per_role(self) -> None:
        # `routing.yaml`'s declared quality_gates per route (standalone mode:
        # Agentic SDLC unavailable, gates pass through as declared). When
        # AGENTIC_SDLC_BIN/agentic-sdlc *is* available (integrated mode, as in
        # CI's python-contracts job), the kernel enriches required_quality_gates
        # to the full cumulative G1..max(declared) sequence, since reaching a
        # later gate implies every earlier one was also required — see
        # test_emits_schema_v2_quality_gates_separately_from_human_gates above
        # for the same cumulative pattern on an unrelated route.
        cases = [
            ("product owner decision package", "product-owner-aide", ["G1", "G2", "G6"]),
            ("engineering lead decision package", "engineering-lead-aide", ["G2", "G6"]),
            ("system architect decision package", "system-architect-aide", ["G3"]),
            ("governance lead decision package", "governance-lead-aide", ["G4"]),
            ("security lead decision package", "security-lead-aide", ["G5"]),
            ("release owner decision package", "release-owner-aide", ["G7", "G8"]),
            ("release authority decision package", "release-authority-aide", ["G9"]),
            ("service owner decision package", "service-owner-aide", ["G10"]),
        ]
        for task, expected_agent, declared_gates in cases:
            with self.subTest(agent=expected_agent):
                result = plan(task=task, changed_files=[])
                self.assertEqual(result["agents"]["primary"], [expected_agent])
                if AGENTIC_SDLC_AVAILABLE:
                    max_gate = max(int(gate[1:]) for gate in declared_gates)
                    expected_gates = [f"G{n}" for n in range(1, max_gate + 1)]
                else:
                    expected_gates = declared_gates
                self.assertEqual(self.quality_gate_ids(result), expected_gates)
                # Aides are read-only preparers, never reviewers or approvers.
                self.assertNotIn(expected_agent, result["agents"]["reviewers"])

    @unittest.skipUnless(AGENTIC_SDLC_AVAILABLE, "Agentic SDLC executable is required")
    def test_selects_runtime_assurance_without_production_release(self) -> None:
        result = plan(task="Observe production runtime for deployed behavior conformance", changed_files=[])
        self.assertEqual(result["workflow"], "runtime-assurance")
        self.assertEqual(result["agents"]["primary"], ["observability-sre"])
        self.assertIn("security-reviewer", result["agents"]["reviewers"])
        self.assertIn("compliance-reviewer", result["agents"]["reviewers"])
        self.assertIn("support-triage-agent", result["agents"]["support"])
        self.assertEqual(self.quality_gate_ids(result), ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10"])
        self.assertNotIn("production-change", [gate["id"] for gate in result["human_gates"]])

    def test_workflow_precedence_keeps_support_ahead_of_runtime_assurance(self) -> None:
        result = plan(
            task="Triage a customer incident during runtime assurance",
            changed_files=["incidents/INC-9.md"],
        )
        self.assertEqual(result["workflow"], "support-escalation")

    def test_runtime_failure_still_uses_debugging_workflow(self) -> None:
        result = plan(task="Debug a production runtime failure", changed_files=["diagnostics/error.log"])
        self.assertEqual(result["workflow"], "debugging")
        self.assertIn("debugging-engineer", result["agents"]["primary"])

    @unittest.skipUnless(AGENTIC_SDLC_AVAILABLE, "Agentic SDLC executable is required")
    def test_narrow_lifecycle_routes_avoid_generic_collisions(self) -> None:
        cases = [
            ("Update README requirements", ["README.md"]),
            ("Review package dependencies", ["services/go.mod"]),
            ("Configure TLS", ["services/api/config.go"]),
            ("Review database data retention", ["database/postgres/backup.md"]),
            ("Fix ordinary runtime behavior", ["services/api/main.go"]),
        ]
        specialist_agents = {
            "governance-planner",
            "data-governance-engineer",
            "cryptographic-assurance-engineer",
        }
        for task, changed_files in cases:
            with self.subTest(task=task):
                result = plan(task=task, changed_files=changed_files)
                selected = {
                    *result["agents"]["primary"],
                    *result["agents"]["reviewers"],
                    *result["agents"]["support"],
                }
                gate_agents = {
                    agent
                    for gate in result["gate_dispatch"]
                    if gate["status"] == "required"
                    for agent in gate["agents"]
                }
                self.assertTrue(gate_agents.issubset(selected))
                self.assertNotEqual(result["workflow"], "runtime-assurance")

    def test_knowledge_invocation_preserves_argv_and_output_contract(self) -> None:
        result = plan(
            task="Update the React navigation",
            changed_files=["frontend/src/Nav.tsx"],
            classification="confidential",
            source="approved-decisions",
            top=3,
            task_id="UI-8",
        )
        request = next(
            request
            for request in result["knowledge_context"]["requests"]
            if request["agent"] == "frontend-engineer"
        )
        self.assertEqual(
            request,
            {
                "agent": "frontend-engineer",
                "query": (
                    "Task: Update the React navigation. Retrieve frontend implementation "
                    "patterns, UX decisions, accessibility behavior, API contracts, "
                    "browser security, and approved React or TypeScript conventions."
                ),
                "invocation": {
                    "launcher": {
                        "runtime": "python",
                        "minimum_version": "3.10",
                        "resolution": "runner-probed",
                    },
                    "args": [
                        str(AGENTS_ROOT / "knowledge-store" / "src" / "cli.py"),
                        "context",
                        "--agent",
                        "frontend-engineer",
                        "--task-id",
                        "UI-8",
                        "--query",
                        (
                            "Task: Update the React navigation. Retrieve frontend implementation "
                            "patterns, UX decisions, accessibility behavior, API contracts, "
                            "browser security, and approved React or TypeScript conventions."
                        ),
                        "--classification",
                        "confidential",
                        "--top",
                        "3",
                        "--source",
                        "approved-decisions",
                    ],
                },
            },
        )

    def test_adds_security_roles_for_authentication_work(self) -> None:
        result = plan(
            task="Add OIDC authentication and session handling to the React frontend",
            changed_files=["frontend/src/auth/session.ts"],
        )
        self.assertIn("frontend-engineer", result["agents"]["primary"])
        self.assertIn("threat-modeler", result["agents"]["support"])
        self.assertIn("security-reviewer", result["agents"]["reviewers"])
        self.assertEqual(result["knowledge_context"]["status"], "authorization-required")

    def test_selects_infrastructure_workflow_and_independent_review(self) -> None:
        result = plan(
            task="Update Terraform for a Proxmox worker VM",
            changed_files=["terraform/modules/worker/main.tf"],
        )
        self.assertEqual(result["workflow"], "infrastructure-change")
        self.assertEqual(result["agents"]["primary"], ["infrastructure-provisioner"])
        self.assertEqual(result["agents"]["reviewers"], ["infrastructure-reviewer"])

    def test_routes_compose_runtime_changes_to_infrastructure_review(self) -> None:
        result = plan(
            task="Fix Podman Compose named volume behavior for PostgreSQL",
            changed_files=["deploy/compose/compose.yaml"],
        )
        self.assertEqual(result["workflow"], "new-service")
        self.assertIn("backend-engineer", result["agents"]["primary"])
        self.assertIn("infrastructure-provisioner", result["agents"]["primary"])
        self.assertIn("infrastructure-reviewer", result["agents"]["reviewers"])

    def test_selects_black_box_tester_for_external_behavior(self) -> None:
        result = plan(
            task="Create black-box end-to-end tests for public API upload behavior",
            changed_files=["tests/features/upload.feature"],
            classification="internal",
            task_id="QA-1",
        )
        self.assertIn("black-box-tester", result["agents"]["primary"])
        self.assertIn("test-engineer", result["agents"]["primary"])
        self.assertEqual(result["knowledge_context"]["status"], "planned")
        self.assertTrue(
            any(request["agent"] == "black-box-tester" for request in result["knowledge_context"]["requests"])
        )

    def test_selects_debugging_engineer_for_root_cause_work(self) -> None:
        result = plan(
            task="Debug a panic and identify the root cause from the stack trace",
            changed_files=["services/internal/repository/regression/panic_test.go"],
            classification="internal",
            task_id="DBG-1",
        )
        self.assertIn("debugging-engineer", result["agents"]["primary"])
        self.assertEqual(result["workflow"], "debugging")
        self.assertIn("test-engineer", result["agents"]["primary"])
        self.assertIn("code-reviewer", result["agents"]["reviewers"])
        self.assertEqual(result["knowledge_context"]["status"], "planned")
        self.assertTrue(
            any(request["agent"] == "debugging-engineer" for request in result["knowledge_context"]["requests"])
        )

    def test_selects_debugging_engineer_for_agent_tune_up(self) -> None:
        result = plan(
            task="Inspect agents, find routing issues, and tune agent definitions",
            changed_files=["agents/orchestration/routing.yaml", "agents/engineering/debugging-engineer/AGENT.md"],
            classification="internal",
            task_id="AGENT-DBG-1",
        )
        self.assertIn("debugging-engineer", result["agents"]["primary"])
        self.assertEqual(result["workflow"], "debugging")
        self.assertIn("application-engineer", result["agents"]["primary"])
        self.assertIn("code-reviewer", result["agents"]["reviewers"])

    def test_selects_debugging_engineer_for_agent_definition_path_only(self) -> None:
        result = plan(
            task="Update role guidance",
            changed_files=["agents/engineering/frontend-engineer/AGENT.md"],
            classification="internal",
            task_id="AGENT-PATH-1",
        )
        self.assertEqual(result["workflow"], "debugging")
        self.assertIn("debugging-engineer", result["agents"]["primary"])
        self.assertIn("technical-writer", result["agents"]["primary"])

    def test_selects_governance_roles_for_agent_suite_review(self) -> None:
        result = plan(
            task="Review project agents skills and structure",
            changed_files=["README.md", "AGENTS.md", ".agents/skills/agent-authoring/SKILL.md"],
            classification="internal",
            task_id="GOV-1",
        )
        self.assertEqual(result["workflow"], "debugging")
        self.assertIn("application-engineer", result["agents"]["primary"])
        self.assertIn("debugging-engineer", result["agents"]["primary"])
        self.assertIn("test-engineer", result["agents"]["reviewers"])
        self.assertIn("code-reviewer", result["agents"]["reviewers"])
        self.assertTrue(
            "technical-writer" in result["agents"]["primary"]
            or "technical-writer" in result["agents"]["support"]
        )
        self.assertNotEqual(result["agents"]["primary"], ["technical-writer"])

    def test_selects_governance_roles_for_publishable_skill_audit(self) -> None:
        result = plan(
            task="Audit publishable skills for packaging and stale references",
            changed_files=[".agents/skills/run-agent-orchestration/SKILL.md"],
            classification="internal",
            task_id="GOV-2",
        )
        self.assertIn("application-engineer", result["agents"]["primary"])
        self.assertIn("debugging-engineer", result["agents"]["primary"])
        self.assertTrue(
            "technical-writer" in result["agents"]["primary"]
            or "technical-writer" in result["agents"]["support"]
        )

    def test_selects_end_user_and_support_for_uat(self) -> None:
        result = plan(
            task="Run UAT for end-user document upload journeys and supportability",
            changed_files=["docs/uat/document-upload.md"],
            classification="internal",
            task_id="UAT-1",
        )
        self.assertIn("end-user-tester", result["agents"]["primary"])
        self.assertIn("technical-writer", result["agents"]["primary"])
        self.assertIn("support-triage-agent", result["agents"]["support"])

    def test_selects_support_triage_and_escalation_manager_with_human_gate(self) -> None:
        result = plan(
            task="Triage a customer report and escalate to human support owner",
            changed_files=["support/tickets/TICKET-123.md"],
            classification="confidential",
            task_id="SUP-123",
        )
        self.assertEqual(result["workflow"], "support-escalation")
        self.assertIn("support-triage-agent", result["agents"]["primary"])
        self.assertIn("escalation-manager", result["agents"]["support"])
        self.assertEqual(
            [gate["id"] for gate in result["human_gates"]],
            ["accountable-human-escalation"],
        )

    def test_selects_observability_sre_for_alerting_and_slos(self) -> None:
        result = plan(
            task="Define SLO alerts and Grafana dashboards for document upload",
            changed_files=["observability/alerts/document-upload.yaml"],
            classification="internal",
            task_id="OBS-1",
        )
        self.assertIn("observability-sre", result["agents"]["primary"])
        self.assertIn("technical-writer", result["agents"]["reviewers"])
        self.assertEqual(result["knowledge_context"]["status"], "planned")

    def test_selects_secrets_identity_with_privileged_human_gate(self) -> None:
        result = plan(
            task="Rotate a production secret for a Kubernetes service account",
            changed_files=["identity/rbac/serviceaccount-api.yaml"],
            classification="restricted",
            task_id="ID-1",
        )
        self.assertIn("secrets-identity-engineer", result["agents"]["primary"])
        self.assertIn("security-reviewer", result["agents"]["reviewers"])
        self.assertIn("privileged-identity-change", [gate["id"] for gate in result["human_gates"]])

    def test_selects_database_reliability_for_postgres_recovery(self) -> None:
        result = plan(
            task="Review PostgreSQL PITR backup and restore readiness",
            changed_files=["database/postgres/backup.md"],
            classification="confidential",
            task_id="DBRE-1",
        )
        self.assertIn("database-reliability-engineer", result["agents"]["primary"])
        self.assertIn("infrastructure-reviewer", result["agents"]["reviewers"])

    def test_selects_policy_as_code_for_admission_controls(self) -> None:
        result = plan(
            task="Add Kyverno policy for restricted security contexts",
            changed_files=["policy/kyverno/restricted.yaml"],
            classification="internal",
            task_id="POL-1",
        )
        self.assertIn("policy-as-code-engineer", result["agents"]["primary"])
        self.assertIn("security-reviewer", result["agents"]["reviewers"])

    def test_selects_supply_chain_reviewer_for_dependency_evidence(self) -> None:
        result = plan(
            task="Review dependency SBOM and container image provenance",
            changed_files=["services/go.mod"],
            classification="internal",
            task_id="SC-1",
        )
        self.assertIn("supply-chain-security-reviewer", result["agents"]["primary"])
        self.assertIn("security-reviewer", result["agents"]["reviewers"])
        self.assertIn("release-engineer", result["agents"]["support"])

    def test_selects_incident_commander_for_major_incident(self) -> None:
        result = plan(
            task="Coordinate a SEV1 major incident and postmortem",
            changed_files=["incidents/SEV1-document-upload.md"],
            classification="confidential",
            task_id="INC-1",
        )
        self.assertEqual(result["workflow"], "support-escalation")
        self.assertIn("incident-commander", result["agents"]["primary"])
        self.assertIn("observability-sre", result["agents"]["support"])

    def test_selects_cost_capacity_planner_for_sizing(self) -> None:
        result = plan(
            task="Estimate Kubernetes resource limits and storage growth headroom",
            changed_files=["capacity/document-upload-sizing.md"],
            classification="internal",
            task_id="CAP-1",
        )
        self.assertIn("cost-capacity-planner", result["agents"]["primary"])
        self.assertIn("observability-sre", result["agents"]["support"])

    def test_selects_finops_engineer_for_cost_drift(self) -> None:
        result = plan(
            task="Investigate a spend anomaly and quota exhaustion drift observed in production",
            changed_files=["reports/anomaly-2026-07.txt"],
        )
        self.assertIn("finops-engineer", result["agents"]["primary"])
        self.assertIn("observability-sre", result["agents"]["support"])
        # The cost-capacity route's bare "quota" keyword also matches this task
        # text, so cost-capacity-planner co-selects as primary alongside
        # finops-engineer. This is deliberate (the two roles hand off to each
        # other per their AGENT.md), so assert it explicitly rather than
        # leaving the overlap unverified.
        self.assertIn("cost-capacity-planner", result["agents"]["primary"])

    def test_selects_api_contract_engineer_for_openapi_changes(self) -> None:
        result = plan(
            task="Add a versioned breaking change to the checkout API contract",
            changed_files=["contracts/checkout/openapi.yaml"],
        )
        self.assertIn("api-contract-engineer", result["agents"]["primary"])
        self.assertIn("cloud-architect", result["agents"]["support"])
        self.assertIn("frontend-engineer", result["agents"]["support"])
        self.assertIn("code-reviewer", result["agents"]["reviewers"])
        # The pre-existing backend route's bare "api" keyword also matches any
        # task text mentioning "API", so backend-engineer co-selects as
        # primary here too. Assert it explicitly (rather than leaving it
        # unverified) since a contract change realistically does need backend
        # implementation awareness; a contracts/** path with no "api" wording
        # in the task text would not pull backend-engineer in.
        self.assertIn("backend-engineer", result["agents"]["primary"])

    def test_frontend_route_includes_accessibility_reviewer(self) -> None:
        result = plan(
            task="Update the React navigation for keyboard accessibility",
            changed_files=["frontend/src/Nav.tsx"],
        )
        self.assertIn("frontend-engineer", result["agents"]["primary"])
        self.assertIn("accessibility-reviewer", result["agents"]["reviewers"])

    def test_selects_engineering_and_review_for_orchestration_config_only(self) -> None:
        result = plan(
            task="Adjust configuration behavior",
            changed_files=["agents/orchestration/routing.yaml"],
        )
        self.assertEqual(result["agents"]["primary"], ["application-engineer", "debugging-engineer"])
        self.assertEqual(result["agents"]["reviewers"], ["test-engineer", "code-reviewer"])

    def test_adds_human_gates_for_production_database_migrations(self) -> None:
        result = plan(
            task="Run a production database migration that alters the users table",
            changed_files=["services/users/migrations/0042_users.sql"],
        )
        self.assertEqual(result["workflow"], "production-release")
        self.assertIn("backend-engineer", result["agents"]["primary"])
        self.assertIn("release-engineer", result["agents"]["support"])
        self.assertEqual(
            [gate["id"] for gate in result["human_gates"]],
            ["persistent-database-migration", "production-change"],
        )

    def test_selects_performance_testing_engineer_for_load_tests(self) -> None:
        result = plan(
            task="Add a load test to measure checkout throughput and latency under peak traffic",
            changed_files=["perf/checkout-load-test.js"],
        )
        self.assertIn("performance-testing-engineer", result["agents"]["primary"])
        self.assertIn("infrastructure-reviewer", result["agents"]["reviewers"])
        self.assertIn("cost-capacity-planner", result["agents"]["support"])

    def test_selects_chaos_resilience_engineer_for_fault_injection(self) -> None:
        result = plan(
            task="Run a game day exercise to inject node failure and verify automated recovery",
            changed_files=["chaos/node-failure-scenario.yaml"],
        )
        self.assertIn("chaos-resilience-engineer", result["agents"]["primary"])
        self.assertIn("infrastructure-reviewer", result["agents"]["reviewers"])
        self.assertIn("cloud-architect", result["agents"]["support"])
        self.assertIn("observability-sre", result["agents"]["support"])

    def test_selects_cloud_architect_as_primary_for_architecture_design(self) -> None:
        result = plan(
            task="Design the architecture for a new document-ingestion service",
            changed_files=["architecture/document-ingestion/adr-0001.md"],
        )
        self.assertIn("cloud-architect", result["agents"]["primary"])
        self.assertIn("threat-modeler", result["agents"]["reviewers"])
        self.assertNotIn("threat-modeler", result["agents"]["support"])

    def test_matched_risks_include_populated_reasons(self) -> None:
        result = plan(
            task="Run a production database migration that alters the users table",
            changed_files=["services/users/migrations/0042_users.sql"],
        )
        matched_risks = {risk["id"]: risk for risk in result["matched_risks"]}
        self.assertIn("database-migration", matched_risks)
        reasons = matched_risks["database-migration"]["reasons"]
        self.assertIsNotNone(reasons)
        self.assertTrue(reasons["keywords"] or reasons["paths"])
        self.assertNotIn("matched", reasons)

    def test_returns_needs_triage_instead_of_guessing(self) -> None:
        result = plan(task="Investigate an unexplained issue", changed_files=["unknown/file.xyz"])
        self.assertEqual(result["status"], "needs-triage")
        self.assertEqual(result["workflow"], "needs-triage")
        self.assertEqual(result["agents"], {"primary": [], "reviewers": [], "support": []})

    def test_generates_stable_task_id(self) -> None:
        first = plan(task="Update Terraform", changed_files=["main.tf"])
        second = plan(task="Update Terraform", changed_files=["main.tf"])
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(first["task_id"], "local-c4361ed30b71")

    def test_routes_orchestrator_source_to_application_engineering(self) -> None:
        result = plan(
            task="Refactor the local agent selector",
            changed_files=["agents/orchestration/src/select_agents.py"],
        )
        self.assertEqual(result["agents"]["primary"], ["application-engineer", "debugging-engineer"])
        self.assertIn("test-engineer", result["agents"]["reviewers"])
        self.assertIn("code-reviewer", result["agents"]["reviewers"])

    def test_orchestration_example_architecture_does_not_select_agent_suite_debugging(self) -> None:
        result = plan(
            task="Resolve architecture decisions for OIDC and PostgreSQL recovery",
            changed_files=["agents/orchestration/examples/example/architecture.md"],
            classification="internal",
            task_id="EXAMPLE-ARCH",
        )
        self.assertEqual(result["workflow"], "new-service")
        self.assertNotIn("debugging-engineer", result["agents"]["primary"])

    def test_explicit_files_support_repeat_comma_and_stable_deduplication(self) -> None:
        self.assertEqual(
            explicit_files(["frontend/a.ts, services/a.go", "frontend/a.ts", "main.tf"]),
            ["frontend/a.ts", "services/a.go", "main.tf"],
        )

    @patch("select_agents._run_git")
    def test_git_status_discovery_preserves_order_and_rename_destination(self, run_git) -> None:
        run_git.return_value = " M frontend/a.ts\0R  infra/new.tf\0old.tf\0?? tests/new.feature\0"
        self.assertEqual(
            discover_changed_files(None),
            {
                "source": "git-status",
                "files": ["frontend/a.ts", "infra/new.tf", "tests/new.feature"],
            },
        )
        run_git.assert_called_once_with(
            ["status", "--short", "-z", "--untracked-files=all"],
            AGENTS_ROOT.parent.resolve(),
        )

    @patch("select_agents._run_git")
    def test_git_status_discovery_preserves_quoted_paths_verbatim(self, run_git) -> None:
        # -z output is never quoted/escaped (unlike plain --short, which
        # octal-escapes non-ASCII/special-character paths under the default
        # core.quotePath) — a path containing a literal " -> " substring or
        # non-ASCII characters must survive intact.
        run_git.return_value = "A  frontend/café -> menu.ts\0?? weird dir/file with spaces.txt\0"
        self.assertEqual(
            discover_changed_files(None),
            {
                "source": "git-status",
                "files": ["frontend/café -> menu.ts", "weird dir/file with spaces.txt"],
            },
        )

    @patch("select_agents._run_git")
    def test_git_base_discovery_uses_three_dot_diff(self, run_git) -> None:
        run_git.return_value = "services/a.go\ninfra/main.tf\n"
        self.assertEqual(
            discover_changed_files("main"),
            {
                "source": "git-diff:main...HEAD",
                "files": ["services/a.go", "infra/main.tf"],
            },
        )
        run_git.assert_called_once_with(["diff", "--name-only", "main...HEAD"], AGENTS_ROOT.parent.resolve())

    def test_origin_slug_supports_common_git_url_forms(self) -> None:
        origins = {
            "https://github.com/Owner/Repository.git": "owner/repository",
            "ssh://git@github.com/Owner/Repository.git": "owner/repository",
            "git@github.com:Owner/Repository.git": "owner/repository",
        }
        for origin, expected in origins.items():
            with self.subTest(origin=origin), patch("select_agents._run_git", return_value=origin):
                self.assertEqual(expected, _origin_slug(AGENTS_ROOT.parent))

    def test_repository_source_falls_back_to_canonical_path_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="Source Repo ") as temporary_directory:
            root = Path(temporary_directory).resolve()
            expected_hash = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
            expected_name = re.sub(r"[^a-z0-9._-]+", "-", root.name.lower()).strip("-")
            with patch("select_agents._run_git", side_effect=RuntimeError("no origin")):
                self.assertEqual(
                    f"local-{expected_name}-{expected_hash}",
                    resolve_knowledge_source(root),
                )

    def test_cli_root_targets_unrelated_git_repository_for_status_and_base(self) -> None:
        selector = ROOT / "src" / "select_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "target"
            caller = Path(temporary_directory) / "caller"
            target.mkdir()
            caller.mkdir()
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(target), "remote", "add", "origin", "https://github.com/Example/TargetRepo.git"],
                check=True,
            )
            (target / "frontend").mkdir()
            (target / "frontend" / "base.tsx").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "add", "."], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "base"], check=True)
            base = subprocess.run(
                ["git", "-C", str(target), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, encoding="utf-8",
            ).stdout.strip()
            (target / "services").mkdir()
            (target / "services" / "api.go").write_text("package services\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "add", "."], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "service"], check=True)
            (target / "frontend" / "base.tsx").write_text("dirty\n", encoding="utf-8")

            common = [sys.executable, str(selector), "--root", str(target), "--task", "Update React and API"]
            status = subprocess.run(common, cwd=caller, check=True, capture_output=True, text=True)
            status_plan = json.loads(status.stdout)
            self.assertEqual(str(target.resolve()), status_plan["inputs"]["repository_root"])
            self.assertEqual("example/targetrepo", status_plan["inputs"]["source_filter"])
            self.assertEqual(["frontend/base.tsx"], status_plan["inputs"]["changed_files"])

            diff = subprocess.run([*common, "--base", base], cwd=caller, check=True, capture_output=True, text=True)
            diff_plan = json.loads(diff.stdout)
            self.assertEqual(str(target.resolve()), diff_plan["inputs"]["repository_root"])
            self.assertEqual("example/targetrepo", diff_plan["inputs"]["source_filter"])
            self.assertEqual(["services/api.go"], diff_plan["inputs"]["changed_files"])

    def test_non_git_root_requires_explicit_files(self) -> None:
        selector = ROOT / "src" / "select_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            implicit = subprocess.run(
                [sys.executable, str(selector), "--root", str(root), "--task", "Update React"],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, implicit.returncode)
            explicit = subprocess.run(
                [sys.executable, str(selector), "--root", str(root), "--task", "Update React", "--files", "frontend/App.tsx"],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual("explicit", json.loads(explicit.stdout)["inputs"]["changed_file_source"])

    def test_conjunctive_production_and_destructive_gates(self) -> None:
        production_phrases = [
            "Apply the Helm chart in production",
            "Rotate credentials in the live environment",
            "Restart the prod service",
        ]
        destructive_phrases = [
            "Delete the Kubernetes namespace",
            "Drop the customer database",
            "Truncate the audit table",
            "Run terraform destroy",
            "Destroy the environment",
            "Wipe the disk",
            "Destroy the VM",
            "wipe the cache",
        ]
        for phrase in production_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn("production-change", [gate["id"] for gate in plan(task=phrase)["human_gates"]])
        for phrase in destructive_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn("destructive-action", [gate["id"] for gate in plan(task=phrase)["human_gates"]])
        for phrase in (
            "Observe production runtime health",
            "Read the production dashboard",
            "Delete a local variable",
            "Evaluate a destroy command example",
            "Inspect a wipe warning",
            "Delete a local variable and rename it",
            "Evaluate a destroy command example, does it work?",
            "Please remove it from the README",
            "Please destroy it",
            "Just delete it",
            "The bug will destroy it eventually",
        ):
            with self.subTest(benign=phrase):
                self.assertNotIn(
                    "production-change",
                    [gate["id"] for gate in plan(task=phrase)["human_gates"]],
                )
                self.assertNotIn(
                    "destructive-action",
                    [gate["id"] for gate in plan(task=phrase)["human_gates"]],
                )

    def test_load_routing_rejects_malformed_keyword_groups(self) -> None:
        for keyword_groups in ("destroy delete", [[]], [["destroy", ""]], [["destroy", 42]]):
            with self.subTest(keyword_groups=keyword_groups):
                config = json.loads((ROOT / "routing.yaml").read_text(encoding="utf-8"))
                config["risk_rules"][-1]["keyword_groups"] = keyword_groups
                with tempfile.TemporaryDirectory() as temporary_directory:
                    path = Path(temporary_directory) / "routing.json"
                    path.write_text(json.dumps(config), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "keyword_groups"):
                        load_routing(path)

    def test_load_routing_rejects_inverted_dynamic_team_range(self) -> None:
        config = json.loads((ROOT / "routing.yaml").read_text(encoding="utf-8"))
        config["team_recipes"][-1]["instances"] = {"min": 4, "max": 2}
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "routing.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "1 <= min <= max"):
                load_routing(path)

    def test_selection_schema_rejects_malformed_closed_contracts(self) -> None:
        import jsonschema

        schema = json.loads((ROOT / "selection.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        valid = plan(
            task="Deploy the API to production",
            changed_files=["services/api/main.go"],
            classification="internal",
            task_id="SCHEMA-1",
        )
        validator.validate(valid)

        malformed = []
        value = json.loads(json.dumps(valid))
        value["inputs"]["unknown"] = True
        malformed.append(value)
        value = json.loads(json.dumps(valid))
        value["matched_risks"][0]["reasons"]["keywords"] = "deploy"
        malformed.append(value)
        value = json.loads(json.dumps(valid))
        value["agents"]["unknown"] = []
        malformed.append(value)
        value = json.loads(json.dumps(valid))
        value["lifecycle_tracking"] = {"status": "integrated", "reason": "not allowed"}
        malformed.append(value)
        value = json.loads(json.dumps(valid))
        value["knowledge_context"]["requests"][0]["invocation"]["unknown"] = True
        malformed.append(value)
        for index, candidate in enumerate(malformed):
            with self.subTest(index=index):
                self.assertTrue(list(validator.iter_errors(candidate)))

    def test_rejects_invalid_classification_for_selected_agents(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid classification: secret"):
            plan(
                task="Update Terraform",
                changed_files=["main.tf"],
                classification="secret",
            )

    def test_rejects_knowledge_top_outside_orchestration_policy(self) -> None:
        for top in (0, 21, "many"):
            with self.subTest(top=top), self.assertRaisesRegex(
                ValueError, "Knowledge top must be an integer from 1 through 20"
            ):
                plan(
                    task="Update Terraform",
                    changed_files=["main.tf"],
                    classification="internal",
                    top=top,
                )

    def test_cli_emits_a_valid_plan_for_explicit_files(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "src" / "select_agents.py"),
                "--task",
                "Change the GitLab pipeline runner configuration",
                "--files",
                ".gitlab-ci.yml",
                "--classification",
                "internal",
                "--task-id",
                "CI-7",
            ],
            cwd=AGENTS_ROOT.parent,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["task_id"], "CI-7")
        self.assertEqual(output["workflow"], "pipeline-change")
        self.assertIn("cicd-engineer", output["agents"]["primary"])
        self.assertIn("pipeline-security-reviewer", output["agents"]["reviewers"])

    def test_cli_emits_utf8_and_writes_output_relative_to_callers_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "src" / "select_agents.py"),
                    "--task",
                    "Añadir navegación React – café",
                    "--files",
                    "frontend/src/Nav.tsx",
                    "--task-id",
                    "UI-UTF8",
                    "--output",
                    "plans/selección.json",
                ],
                cwd=temporary_directory,
                check=False,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stdout, b"")
            output_path = Path(temporary_directory) / "plans" / "selección.json"
            raw_output = output_path.read_bytes()
            self.assertIn("Añadir navegación React – café".encode("utf-8"), raw_output)
            self.assertTrue(raw_output.endswith(b"\n"))
            self.assertEqual(json.loads(raw_output.decode("utf-8"))["task_id"], "UI-UTF8")

    def test_cli_stdout_is_utf8(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "src" / "select_agents.py"),
                "--task",
                "Añadir navegación React – café",
                "--files",
                "frontend/src/Café.tsx",
                "--task-id",
                "UI-STDOUT-UTF8",
            ],
            cwd=AGENTS_ROOT.parent,
            check=False,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        decoded = result.stdout.decode("utf-8", errors="strict")
        self.assertIn("Añadir navegación React – café", decoded)
        self.assertIn("frontend/src/Café.tsx", decoded)
        self.assertTrue(result.stdout.endswith(b"\n"))

    @patch("build_dispatch_plan.try_lifecycle_contract", return_value=None)
    def test_standalone_mode_still_dispatches_teams_without_agentic_sdlc(self, _mock) -> None:
        result = plan(
            task="Add a React upload form backed by a PostgreSQL API",
            changed_files=["frontend/src/Upload.tsx", "services/upload/main.go"],
            classification="internal",
            task_id="STANDALONE-1",
        )
        from build_dispatch_plan import STANDALONE_REASON

        self.assertEqual(result["lifecycle_tracking"], {"status": "standalone", "reason": STANDALONE_REASON})
        self.assertEqual(result["agents"]["primary"], ["frontend-engineer", "backend-engineer"])
        self.assertIn("test-engineer", result["agents"]["reviewers"])
        self.assertEqual(result["gate_dispatch"], [])

    @patch("build_dispatch_plan.try_lifecycle_contract", return_value=None)
    def test_standalone_mode_still_reports_needs_triage(self, _mock) -> None:
        result = plan(task="Investigate an unexplained issue", changed_files=["unknown/file.xyz"])
        self.assertEqual(result["status"], "needs-triage")
        self.assertEqual(result["lifecycle_tracking"]["status"], "standalone")

    @patch(
        "build_dispatch_plan.require_lifecycle_contract",
        side_effect=RuntimeError(agentic_sdlc_contracts.INSTALL_MESSAGE),
    )
    def test_require_sdlc_fails_fast_without_agentic_sdlc(self, _mock) -> None:
        with self.assertRaisesRegex(RuntimeError, "Agentic SDLC v0.3.x is required"):
            build_dispatch_plan(
                CONFIG,
                CATALOG,
                {
                    "task": "Update Terraform",
                    "changed_files": ["main.tf"],
                    "changed_file_source": "test",
                    "repository_root": str(AGENTS_ROOT.parent),
                    "source": "example/repository",
                },
                require_sdlc=True,
            )

    @patch("agentic_sdlc_contracts._resolve_executable", return_value=None)
    def test_agentic_sdlc_contracts_try_returns_none_when_unresolved(self, _mock) -> None:
        agentic_sdlc_contracts._fetch_contract.cache_clear()
        self.assertIsNone(agentic_sdlc_contracts.try_lifecycle_contract())
        with self.assertRaisesRegex(RuntimeError, "Agentic SDLC v0.3.x is required"):
            agentic_sdlc_contracts.require_lifecycle_contract()

    def test_resolved_lifecycle_executable_failures_never_degrade(self) -> None:
        cases = [
            (
                subprocess.CompletedProcess(["kernel"], 2, "", "contract unavailable"),
                "contract lookup failed",
            ),
            (
                subprocess.CompletedProcess(["kernel"], 0, "not json", ""),
                "malformed JSON",
            ),
            (
                subprocess.CompletedProcess(["kernel"], 0, '{"version": 1, "gates": []}', ""),
                "incompatible",
            ),
        ]
        for completed, message in cases:
            with self.subTest(message=message):
                agentic_sdlc_contracts._fetch_contract.cache_clear()
                with (
                    patch("agentic_sdlc_contracts._resolve_executable", return_value="/fake/kernel"),
                    patch("agentic_sdlc_contracts.subprocess.run", return_value=completed),
                    self.assertRaisesRegex(RuntimeError, message),
                ):
                    agentic_sdlc_contracts.try_lifecycle_contract()

    def test_resolved_lifecycle_timeout_is_actionable(self) -> None:
        agentic_sdlc_contracts._fetch_contract.cache_clear()
        with (
            patch("agentic_sdlc_contracts._resolve_executable", return_value="/fake/kernel"),
            patch(
                "agentic_sdlc_contracts.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["/fake/kernel"], 10),
            ),
            self.assertRaisesRegex(RuntimeError, "timed out"),
        ):
            agentic_sdlc_contracts.try_lifecycle_contract()


if __name__ == "__main__":
    unittest.main()
