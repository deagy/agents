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


def plan(**overrides: object) -> dict[str, object]:
    values = {
        "task": "Change the application",
        "changed_files": [],
        "changed_file_source": "test",
        **overrides,
    }
    return build_dispatch_plan(CONFIG, CATALOG, values)


class SelectorTests(unittest.TestCase):
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
        self.assertTrue(all(request["invocation"]["executable"] == "node" for request in requests))
        self.assertTrue(all(request["invocation"]["args"][:2] == ["src/cli.mjs", "context"] for request in requests))

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
                    "executable": "node",
                    "args": [
                        "src/cli.mjs",
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
