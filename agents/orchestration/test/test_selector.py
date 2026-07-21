"""Regression tests for the dependency-free Python selector."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from build_dispatch_plan import build_dispatch_plan  # noqa: E402
from routing import glob_to_regex, load_catalog, load_routing  # noqa: E402
from select_agents import discover_changed_files, explicit_files  # noqa: E402

CONFIG = load_routing(ROOT / "routing.yaml")
CATALOG = load_catalog(AGENTS_ROOT / "catalog.yaml")


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
        **overrides,
    }
    return build_dispatch_plan(CONFIG, CATALOG, values)


class SelectorTests(unittest.TestCase):
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
        self.assertTrue(all(request["invocation"]["args"][:2] == ["src/cli.py", "context"] for request in requests))

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
                    "Task: Update the React navigation. Retrieve React patterns, UX decisions, "
                    "accessibility, API contracts, and browser security."
                ),
                "invocation": {
                    "cwd": "agents/knowledge-store",
                    "launcher": {
                        "runtime": "python",
                        "minimum_version": "3.10",
                        "resolution": "runner-probed",
                    },
                    "args": [
                        "src/cli.py",
                        "context",
                        "--agent",
                        "frontend-engineer",
                        "--task-id",
                        "UI-8",
                        "--query",
                        (
                            "Task: Update the React navigation. Retrieve React patterns, UX decisions, "
                            "accessibility, API contracts, and browser security."
                        ),
                        "--classification",
                        "confidential",
                        "--top",
                        "3",
                        "--config",
                        "config.json",
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
            changed_files=["sample-001/deploy/compose/compose.yaml"],
        )
        self.assertEqual(result["workflow"], "new-service")
        self.assertIn("backend-engineer", result["agents"]["primary"])
        self.assertIn("infrastructure-provisioner", result["agents"]["primary"])
        self.assertIn("infrastructure-reviewer", result["agents"]["reviewers"])

    def test_selects_black_box_tester_for_external_behavior(self) -> None:
        result = plan(
            task="Create black-box end-to-end tests for public API upload behavior",
            changed_files=["sample-001/tests/features/upload.feature"],
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
            changed_files=["sample-001/services/internal/repository/regression/panic_test.go"],
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
            changed_files=["sample-001/services/go.mod"],
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

    def test_selects_engineering_and_review_for_orchestration_config_only(self) -> None:
        result = plan(
            task="Adjust configuration behavior",
            changed_files=["agents/orchestration/routing.yaml"],
        )
        self.assertEqual(result["agents"]["primary"], ["application-engineer"])
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
        self.assertEqual(result["agents"]["primary"], ["application-engineer"])
        self.assertIn("test-engineer", result["agents"]["reviewers"])
        self.assertIn("code-reviewer", result["agents"]["reviewers"])

    def test_explicit_files_support_repeat_comma_and_stable_deduplication(self) -> None:
        self.assertEqual(
            explicit_files(["frontend/a.ts, services/a.go", "frontend/a.ts", "main.tf"]),
            ["frontend/a.ts", "services/a.go", "main.tf"],
        )

    @patch("select_agents._run_git")
    def test_git_status_discovery_preserves_order_and_rename_destination(self, run_git) -> None:
        run_git.return_value = " M frontend/a.ts\nR  old.tf -> infra/new.tf\n?? tests/new.feature\n"
        self.assertEqual(
            discover_changed_files(None),
            {
                "source": "git-status",
                "files": ["frontend/a.ts", "infra/new.tf", "tests/new.feature"],
            },
        )
        run_git.assert_called_once_with(["status", "--short"])

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
        run_git.assert_called_once_with(["diff", "--name-only", "main...HEAD"])

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


if __name__ == "__main__":
    unittest.main()
