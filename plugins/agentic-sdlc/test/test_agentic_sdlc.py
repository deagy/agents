import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "scripts" / "agentic_sdlc.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import agentic_sdlc  # type: ignore
try:
    import jsonschema  # type: ignore
except ImportError:
    JSONSCHEMA_AVAILABLE = False
else:
    JSONSCHEMA_AVAILABLE = True


class PortableCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments, expected=0):
        result = subprocess.run(
            [sys.executable, str(CLI), *arguments, "--root", str(self.root)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        stream = result.stdout if result.stdout.strip() else result.stderr
        return json.loads(stream)

    def init(self, *extra):
        return self.run_cli("init", "--profile", "generic", *extra)

    def load(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def test_detect_is_read_only(self):
        (self.root / "go.mod").write_text("module example.invalid/demo\n", encoding="utf-8")
        (self.root / "cmd").mkdir()
        result = self.run_cli("detect")
        self.assertIn("go", result["detected_stacks"])
        self.assertEqual("web-service", result["proposed_profile"])
        self.assertFalse((self.root / ".agentic-sdlc").exists())

    def test_detect_proposes_quick_absent_a_stronger_signal(self):
        (self.root / "README.md").write_text("# demo\n", encoding="utf-8")
        result = self.run_cli("detect")
        self.assertEqual("quick", result["proposed_profile"])

    def test_init_auto_profile_defaults_to_quick(self):
        result = self.run_cli("init", "--profile", "auto")
        self.assertEqual("initialized", result["status"])
        self.assertEqual("quick", result["profile"])
        project = self.load(".agentic-sdlc/project.json")
        self.assertEqual("quick", project["profile"])

    def test_quick_profile_change_work_requires_intent_and_requirements(self):
        self.run_cli("init", "--profile", "quick")
        plan = self.run_cli("plan", "--task-id", "QUICK-1", "--task", "Fix a failing login test")
        self.assertEqual(["G1", "G2"], [gate["id"] for gate in plan["required_quality_gates"]])
        self.assertIn("product-intent-agent", plan["agents"]["support"])
        self.assertIn("requirements-agent", plan["agents"]["support"])
        self.assertEqual([], plan["human_gates"])

    def test_quick_profile_non_change_question_has_no_quality_gates(self):
        self.run_cli("init", "--profile", "quick")
        plan = self.run_cli("plan", "--task-id", "QUICK-1B", "--task", "Explain the local validation command")
        self.assertEqual([], plan["required_quality_gates"])

    def test_quick_profile_still_enforces_mutation_gates(self):
        self.run_cli("init", "--profile", "quick")
        plan = self.run_cli("plan", "--task-id", "QUICK-2", "--task", "Prepare a production deployment for the backend API")
        self.assertIn("production-deployment", [gate["id"] for gate in plan["human_gates"]])

    def test_runner_flag_selects_which_wrapper_set_is_generated(self):
        self.run_cli("init", "--profile", "quick", "--runner", "claude")
        self.assertTrue((self.root / ".claude" / "agents" / "security-reviewer.md").exists())
        self.assertFalse((self.root / ".codex").exists())

    def test_secure_cloud_profile_covers_all_34_catalog_roles(self):
        catalog_path = PLUGIN_ROOT.parents[1] / "agents" / "catalog.yaml"
        catalog_ids = {
            line.strip().rstrip(":")
            for line in catalog_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":")
        }
        self.run_cli("init", "--profile", "secure-cloud", "--runner", "claude")
        generated_ids = {path.stem for path in (self.root / ".claude" / "agents").glob("*.md")}
        self.assertEqual(catalog_ids, generated_ids)

    def test_secure_cloud_profile_bakes_in_real_role_content(self):
        self.run_cli("init", "--profile", "secure-cloud", "--runner", "claude")
        wrapper = (self.root / ".claude" / "agents" / "backend-engineer.md").read_text(encoding="utf-8")
        self.assertIn("## Authority", wrapper)
        self.assertIn("pgx", wrapper)
        self.assertNotIn("Act as the portable Agentic SDLC role", wrapper)
        self.assertIn("You are a dispatched subagent", wrapper)

    def test_non_secure_cloud_profiles_are_unaffected_by_rich_content_availability(self):
        self.run_cli("init", "--profile", "generic", "--runner", "claude")
        wrapper = (self.root / ".claude" / "agents" / "application-engineer.md").read_text(encoding="utf-8")
        self.assertIn("Act as the portable Agentic SDLC role application-engineer", wrapper)

    def test_secure_cloud_profile_falls_back_to_generic_stub_without_sibling_plugin(self):
        with tempfile.TemporaryDirectory() as isolated_parent:
            isolated_plugin = Path(isolated_parent) / "agentic-sdlc"
            shutil.copytree(PLUGIN_ROOT, isolated_plugin)
            isolated_cli = isolated_plugin / "scripts" / "agentic_sdlc.py"
            result = subprocess.run(
                [sys.executable, str(isolated_cli), "init", "--profile", "secure-cloud", "--runner", "claude", "--root", str(self.root)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        wrapper = (self.root / ".claude" / "agents" / "backend-engineer.md").read_text(encoding="utf-8")
        self.assertIn("Act as the portable Agentic SDLC role backend-engineer", wrapper)

    def test_init_creates_overlay_wrappers_and_preserves_agents_content(self):
        original = "# Existing rules\n\nKeep this.\n"
        (self.root / "AGENTS.md").write_text(original, encoding="utf-8")
        result = self.init("--extension", "sqs-platform")
        self.assertEqual("initialized", result["status"])
        for name in ["project.json", "authorities.json", "impact-profile.json", "routing.json", "commands.json", "version.lock"]:
            self.assertTrue((self.root / ".agentic-sdlc" / name).exists())
        self.assertTrue((self.root / ".agentic-sdlc" / "runs").is_dir())
        self.assertTrue((self.root / ".codex" / "agents" / "security-reviewer.toml").exists())
        self.assertTrue((self.root / ".claude" / "agents" / "security-reviewer.md").exists())
        claude_wrapper = (self.root / ".claude" / "agents" / "security-reviewer.md").read_text(encoding="utf-8")
        self.assertIn("name: security-reviewer", claude_wrapper)
        self.assertIn("cannot ask the human directly", claude_wrapper)
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Keep this.", agents)
        self.assertEqual(1, agents.count("<!-- agentic-sdlc:start -->"))
        impact = self.load(".agentic-sdlc/impact-profile.json")
        self.assertTrue(impact["blocking_unknowns"])
        self.assertIn("QBOM", [item["id"] for item in impact["specialized_boms"]])
        authorities = self.load(".agentic-sdlc/authorities.json")
        self.assertEqual("unknown", authorities["human_key_owner"]["applicability"])
        self.assertEqual("unknown", authorities["uat_product_owner"]["applicability"])

    def test_reinitialization_does_not_overwrite_unrelated_or_wrapper_content(self):
        self.init()
        wrapper = self.root / ".codex" / "agents" / "security-reviewer.toml"
        wrapper.write_text("# local customization\n", encoding="utf-8")
        with (self.root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write("\nTeam-specific tail.\n")
        self.init("--force")
        self.assertEqual("# local customization\n", wrapper.read_text(encoding="utf-8"))
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Team-specific tail.", agents)
        self.assertEqual(1, agents.count("<!-- agentic-sdlc:start -->"))

    @unittest.skipUnless(JSONSCHEMA_AVAILABLE, "full validation dependency is unavailable")
    def test_validate_fails_closed_for_unknown_authority_and_applicability(self):
        self.init()
        result = self.run_cli("validate", expected=2)
        self.assertTrue(result["valid"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("authority product_owner" in blocker for blocker in result["blockers"]))
        self.assertTrue(any("impact applicability is unknown" in blocker for blocker in result["blockers"]))
        self.assertTrue(any("environment persistence is unknown" in blocker for blocker in result["blockers"]))
        self.assertIn("detected project commands are not confirmed", result["blockers"])

    def test_validate_fails_closed_without_schema_dependency(self):
        self.init()
        result = subprocess.run(
            [sys.executable, "-S", str(CLI), "validate", "--root", str(self.root)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["valid"])
        self.assertTrue(any("validation dependency is unavailable" in error for error in payload["errors"]))

    def test_plan_product_intake_never_approves_and_separates_reviewers(self):
        self.init()
        plan = self.run_cli("plan", "--task-id", "DEMO-1", "--task", "Perform requirements decomposition and requirements traceability")
        self.assertEqual("product-intake", plan["workflow"])
        self.assertEqual([], list(set(plan["agents"]["primary"]) & set(plan["agents"]["reviewers"])))
        record = self.load(".agentic-sdlc/runs/DEMO-1/run-record.json")
        self.assertEqual([f"G{i}" for i in range(1, 11)], [gate["gate_id"] for gate in record["lifecycle_gates"]])
        self.assertNotIn("approved", [gate["status"] for gate in record["lifecycle_gates"]])
        self.assertEqual([], [approval for gate in record["lifecycle_gates"] for approval in gate["human_approvals"]])

    def test_intent_plus_architecture_selects_new_service(self):
        self.init()
        plan = self.run_cli("plan", "--task-id", "DEMO-2", "--task", "Capture product intent and create the service architecture")
        self.assertEqual("new-service", plan["workflow"])
        self.assertEqual(["G1", "G2", "G3"], [gate["id"] for gate in plan["required_quality_gates"]])

    def test_human_mutation_gate_is_separate(self):
        self.init()
        plan = self.run_cli("plan", "--task-id", "DEMO-3", "--task", "Prepare a production deployment for the backend API")
        self.assertEqual("production-release", plan["workflow"])
        self.assertIn("production-deployment", [gate["id"] for gate in plan["human_gates"]])
        self.assertNotIn("production-deployment", [gate["id"] for gate in plan["required_quality_gates"]])
        self.assertEqual(["G8", "G9"], [gate["id"] for gate in plan["required_quality_gates"]])
        self.assertTrue(all(gate["contributing_routes"] for gate in plan["required_quality_gates"]))
        self.assertIn("release-engineer", plan["agents"]["support"])

    @unittest.skipUnless(JSONSCHEMA_AVAILABLE, "full validation dependency is unavailable")
    def test_generated_production_dispatch_conforms_to_schema(self):
        import jsonschema
        self.init()
        dispatch = self.run_cli("plan", "--task-id", "PROD-SCHEMA", "--task", "Prepare a production deployment")
        schema = json.loads((PLUGIN_ROOT / "contracts" / "selection.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(dispatch)

    def test_init_rejects_incomplete_managed_agents_block(self):
        (self.root / "AGENTS.md").write_text("<!-- agentic-sdlc:start -->\n", encoding="utf-8")
        result = self.run_cli("init", "--profile", "generic", expected=1)
        self.assertIn("incomplete Agentic SDLC managed block", result["error"])

    def test_invalidate_preserves_approval_history_and_invalidates_downstream(self):
        self.init()
        self.run_cli("plan", "--task-id", "DEMO-4", "--task", "Create the service architecture")
        path = self.root / ".agentic-sdlc" / "runs" / "DEMO-4" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        old_approval = {
            "status": "approved",
            "approver": {"kind": "human", "id": "old", "role": "Engineering Lead"},
            "decided_at": "2026-07-21T00:00:00Z",
            "evidence_refs": [],
        }
        record["lifecycle_gates"][5]["human_approvals"] = [old_approval]
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("invalidate", "--task-id", "DEMO-4", "--earliest-gate", "G5", "--reason", "Material interface change", "--actor", "engineering-lead")
        self.assertEqual([f"G{i}" for i in range(5, 11)], result["invalidated_gate_ids"])
        record = self.load(".agentic-sdlc/runs/DEMO-4/run-record.json")
        self.assertEqual("security-crypto", record["current_lifecycle_phase"])
        self.assertTrue(all(gate["status"] == "invalidated" for gate in record["lifecycle_gates"][4:]))
        self.assertEqual([old_approval], record["lifecycle_gates"][5]["human_approvals"])
        self.assertEqual("engineering-lead", record["re_entry_history"][0]["actor"])

    def test_status_reports_gate_state(self):
        self.init()
        self.run_cli("plan", "--task-id", "DEMO-5", "--task", "Create the service architecture")
        result = self.run_cli("status", "--task-id", "DEMO-5")
        self.assertEqual("DEMO-5", result["task_id"])
        self.assertEqual(10, len(result["gates"]))

    def test_status_advances_to_next_applicable_gate_phase(self):
        self.init()
        self.run_cli("plan", "--task-id", "DEMO-5B", "--task", "Fix a failing login test")
        path = self.root / ".agentic-sdlc" / "runs" / "DEMO-5B" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["current_lifecycle_phase"] = "requirements"
        record["lifecycle_gates"][0]["status"] = "approved"
        record["lifecycle_gates"][1]["status"] = "approved"
        for index in (2, 3, 4, 6, 7, 8, 9):
            record["lifecycle_gates"][index]["applicability"] = "not-applicable"
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("status", "--task-id", "DEMO-5B")
        self.assertEqual("verify", result["current_phase"])

    def test_validate_rejects_author_reviewer_overlap(self):
        self.init()
        routing_path = self.root / ".agentic-sdlc" / "routing.json"
        routing = json.loads(routing_path.read_text(encoding="utf-8"))
        routing["routes"][0]["reviewers"] = [routing["routes"][0]["agents"][0]]
        routing_path.write_text(json.dumps(routing), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertFalse(result["valid"])
        self.assertTrue(any("author and reviewer" in error for error in result["errors"]))

    def test_changed_task_text_cannot_reuse_task_id(self):
        self.init()
        self.run_cli("plan", "--task-id", "STABLE-1", "--task", "Capture product intent")
        result = self.run_cli("plan", "--task-id", "STABLE-1", "--task", "Deploy to production", expected=1)
        self.assertIn("different task text", result["error"])
        dispatch = self.load(".agentic-sdlc/runs/STABLE-1/dispatch-plan.json")
        self.assertEqual("Capture product intent", dispatch["inputs"]["task"])

    def test_run_record_prevents_dispatch_recreation_with_changed_task(self):
        self.init()
        self.run_cli("plan", "--task-id", "STABLE-2", "--task", "Capture product intent")
        (self.root / ".agentic-sdlc" / "runs" / "STABLE-2" / "dispatch-plan.json").unlink()
        result = self.run_cli("plan", "--task-id", "STABLE-2", "--task", "Deploy to production", expected=1)
        self.assertIn("different task text", result["error"])

    def test_same_task_id_rejects_changed_routing_state(self):
        self.init()
        task = "Capture product intent"
        self.run_cli("plan", "--task-id", "STABLE-3", "--task", task)
        routing_path = self.root / ".agentic-sdlc" / "routing.json"
        routing = json.loads(routing_path.read_text(encoding="utf-8"))
        routing["routes"][0]["gates"].append("G10")
        routing_path.write_text(json.dumps(routing), encoding="utf-8")
        result = self.run_cli("plan", "--task-id", "STABLE-3", "--task", task, expected=1)
        self.assertIn("routing", result["error"])

    def test_task_id_rejects_lossy_aliases(self):
        self.init()
        for task_id in ("TEAM/A", "TEAM?A"):
            with self.subTest(task_id=task_id):
                result = self.run_cli("plan", "--task-id", task_id, "--task", "Capture product intent", expected=1)
                self.assertIn("non-lossy", result["error"])
        self.assertFalse((self.root / ".agentic-sdlc" / "runs" / "TEAM-A").exists())

    def test_plan_rejects_run_directory_symlink_escape_when_supported(self):
        self.init()
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        runs = self.root / ".agentic-sdlc" / "runs"
        runs.rmdir()
        try:
            os.symlink(outside.name, runs, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory symlinks unavailable: {error}")
        result = self.run_cli("plan", "--task-id", "ESCAPE", "--task", "Capture product intent", expected=1)
        self.assertIn("escapes root", result["error"])
        self.assertFalse((Path(outside.name) / "ESCAPE" / "dispatch-plan.json").exists())

    def test_generated_record_conforms_to_bundled_schema_when_jsonschema_available(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("optional jsonschema is unavailable")
        self.init()
        self.run_cli("plan", "--task-id", "SCHEMA-1", "--task", "Create the service architecture")
        record = self.load(".agentic-sdlc/runs/SCHEMA-1/run-record.json")
        self.assertEqual([f"G{i}" for i in range(1, 11)], list(record["execution_summary"]["gates"]))
        self.assertTrue(record["execution_summary"]["gates"]["G1"]["configured"])
        self.assertEqual([], record["execution_summary"]["gates"]["G1"]["dispatched_agents"])
        schema = json.loads((PLUGIN_ROOT / "contracts" / "run-record.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        ).validate(record)

    def test_validate_rejects_malformed_date_time_with_full_validator(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("optional jsonschema is unavailable")
        self.init()
        self.run_cli("plan", "--task-id", "BAD-DATE", "--task", "Create the service architecture")
        path = self.root / ".agentic-sdlc" / "runs" / "BAD-DATE" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["recorded_at"] = "not-a-date"
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("schema recorded_at" in error for error in result["errors"]))

    def test_validate_rejects_unassigned_approver_identity_and_missing_decision_metadata(self):
        self.init()
        authority_path = self.root / ".agentic-sdlc" / "authorities.json"
        authorities = json.loads(authority_path.read_text(encoding="utf-8"))
        authorities["product_owner"].update({"status": "assigned", "assignee": "expected-owner"})
        authority_path.write_text(json.dumps(authorities), encoding="utf-8")
        self.run_cli("plan", "--task-id", "BAD-AUTH", "--task", "Capture product intent")
        path = self.root / ".agentic-sdlc" / "runs" / "BAD-AUTH" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        evidence = {"evidence_id": "E-1", "uri": "repo:evidence", "hash_algorithm": "sha256", "hash": "1", "classification": "internal"}
        gate = record["lifecycle_gates"][0]
        gate.update({
            "status": "approved",
            "artifact_bindings": [{"artifact_id": "A-1", "revision": "1", "digest": "sha256:1", "environment": None}],
            "preparers": [{"id": "intent-author", "role": "product-intent-agent", "kind": "agent"}],
            "independent_verifier": {"id": "reviewer", "role": "code-reviewer", "kind": "agent"},
            "independence_declaration": {"verifier_confirmed_not_preparer": True, "verifier_made_material_correction": False},
            "evidence_refs": [evidence],
            "decided_at": None,
            "human_approvals": [{"status": "approved", "approver": {"id": "intruder", "role": "Product Owner", "kind": "human"}, "decided_at": None, "evidence_refs": []}],
        })
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("not bound to assigned authority product_owner" in error for error in result["errors"]))
        self.assertTrue(any("approval lacks decision time or approval evidence" in error for error in result["errors"]))
        self.assertTrue(any("approved without a gate decision timestamp" in error for error in result["errors"]))

    def test_approve_from_github_records_evidence_and_advances_ready_gate(self):
        self.init()
        authority_path = self.root / ".agentic-sdlc" / "authorities.json"
        authorities = json.loads(authority_path.read_text(encoding="utf-8"))
        authorities["product_owner"].update({
            "status": "assigned",
            "assignee": "github.com/octocat",
            "github_login": "octocat",
        })
        authority_path.write_text(json.dumps(authorities), encoding="utf-8")
        project_path = self.root / ".agentic-sdlc" / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["approval_sources"] = {"human_gate_default": "github-review", "allow_manual_fallback": False}
        project_path.write_text(json.dumps(project), encoding="utf-8")
        self.run_cli("plan", "--task-id", "GH-APPROVE", "--task", "Capture product intent")
        path = self.root / ".agentic-sdlc" / "runs" / "GH-APPROVE" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        gate = record["lifecycle_gates"][0]
        gate.update({
            "status": "ready",
            "artifact_bindings": [{"artifact_id": "A-1", "revision": "abc123", "digest": "sha256:1", "environment": None}],
            "preparers": [{"id": "intent-author", "role": "product-intent-agent", "kind": "agent"}],
            "independent_verifier": {"id": "reviewer", "role": "code-reviewer", "kind": "agent"},
            "independence_declaration": {"verifier_confirmed_not_preparer": True, "verifier_made_material_correction": False},
            "evidence_refs": [{"evidence_id": "E-1", "uri": "repo:evidence", "hash_algorithm": "sha256", "hash": "1", "classification": "internal"}],
        })
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli(
            "approve-from-github",
            "--task-id",
            "GH-APPROVE",
            "--gate",
            "G1",
            "--role",
            "product_owner",
            "--repo",
            "example/repo",
            "--pr",
            "12",
            "--review-id",
            "34",
            "--reviewer-login",
            "octocat",
            "--commit-sha",
            "deadbeef",
            "--decided-at",
            "2030-01-01T00:00:00Z",
        )
        self.assertEqual("approved", result["gate_status"])
        self.assertEqual("requirements", result["current_phase"])
        updated = json.loads(path.read_text(encoding="utf-8"))
        approval = updated["lifecycle_gates"][0]["human_approvals"][0]
        self.assertEqual("github-review:example/repo:pull/12:review/34:reviewer/octocat", approval["evidence_refs"][0]["uri"])
        self.assertEqual("github.com/octocat", approval["approver"]["id"])

    def test_validate_rejects_non_github_approval_when_project_requires_github_reviews(self):
        self.init()
        authority_path = self.root / ".agentic-sdlc" / "authorities.json"
        authorities = json.loads(authority_path.read_text(encoding="utf-8"))
        authorities["product_owner"].update({
            "status": "assigned",
            "assignee": "github.com/octocat",
            "github_login": "octocat",
        })
        authority_path.write_text(json.dumps(authorities), encoding="utf-8")
        project_path = self.root / ".agentic-sdlc" / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["approval_sources"] = {"human_gate_default": "github-review", "allow_manual_fallback": False}
        project_path.write_text(json.dumps(project), encoding="utf-8")
        self.run_cli("plan", "--task-id", "GH-STRICT", "--task", "Capture product intent")
        path = self.root / ".agentic-sdlc" / "runs" / "GH-STRICT" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        evidence = {"evidence_id": "E-1", "uri": "repo:evidence", "hash_algorithm": "sha256", "hash": "1", "classification": "internal"}
        gate = record["lifecycle_gates"][0]
        gate.update({
            "status": "approved",
            "artifact_bindings": [{"artifact_id": "A-1", "revision": "1", "digest": "sha256:1", "environment": None}],
            "preparers": [{"id": "intent-author", "role": "product-intent-agent", "kind": "agent"}],
            "independent_verifier": {"id": "reviewer", "role": "code-reviewer", "kind": "agent"},
            "independence_declaration": {"verifier_confirmed_not_preparer": True, "verifier_made_material_correction": False},
            "evidence_refs": [evidence],
            "decided_at": "2030-01-01T00:00:00Z",
            "human_approvals": [{
                "status": "approved",
                "approver": {"id": "github.com/octocat", "role": "Product Owner", "kind": "human"},
                "decided_at": "2030-01-01T00:00:00Z",
                "evidence_refs": [evidence],
            }],
        })
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("approval must be backed by a GitHub review" in error for error in result["errors"]))

    def test_validate_rejects_github_review_login_mismatch(self):
        self.init()
        authority_path = self.root / ".agentic-sdlc" / "authorities.json"
        authorities = json.loads(authority_path.read_text(encoding="utf-8"))
        authorities["product_owner"].update({
            "status": "assigned",
            "assignee": "github.com/octocat",
            "github_login": "octocat",
        })
        authority_path.write_text(json.dumps(authorities), encoding="utf-8")
        self.run_cli("plan", "--task-id", "GH-MISMATCH", "--task", "Capture product intent")
        path = self.root / ".agentic-sdlc" / "runs" / "GH-MISMATCH" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        gate = record["lifecycle_gates"][0]
        gate.update({
            "status": "approved",
            "artifact_bindings": [{"artifact_id": "A-1", "revision": "1", "digest": "sha256:1", "environment": None}],
            "preparers": [{"id": "intent-author", "role": "product-intent-agent", "kind": "agent"}],
            "independent_verifier": {"id": "reviewer", "role": "code-reviewer", "kind": "agent"},
            "independence_declaration": {"verifier_confirmed_not_preparer": True, "verifier_made_material_correction": False},
            "evidence_refs": [{"evidence_id": "E-1", "uri": "repo:evidence", "hash_algorithm": "sha256", "hash": "1", "classification": "internal"}],
            "decided_at": "2030-01-01T00:00:00Z",
            "human_approvals": [{
                "status": "approved",
                "approver": {"id": "github.com/octocat", "role": "Product Owner", "kind": "human"},
                "decided_at": "2030-01-01T00:00:00Z",
                "evidence_refs": [{
                    "evidence_id": "AE-1",
                    "uri": "github-review:example/repo:pull/12:review/34:reviewer/not-octocat",
                    "hash_algorithm": "sha256",
                    "hash": "2",
                    "classification": "internal",
                }],
            }],
        })
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("GitHub review login does not match approver identity" in error for error in result["errors"]))
        self.assertTrue(any("approval GitHub reviewer does not match assigned authority product_owner" in error for error in result["errors"]))

    def test_select_github_review_prefers_latest_matching_approval(self):
        reviews = [
            {
                "id": 10,
                "state": "APPROVED",
                "submitted_at": "2030-01-01T00:00:00Z",
                "commit_id": "aaa111",
                "user": {"login": "octocat"},
            },
            {
                "id": 11,
                "state": "COMMENTED",
                "submitted_at": "2030-01-02T00:00:00Z",
                "commit_id": "bbb222",
                "user": {"login": "octocat"},
            },
            {
                "id": 12,
                "state": "APPROVED",
                "submitted_at": "2030-01-03T00:00:00Z",
                "commit_id": "ccc333",
                "user": {"login": "octocat"},
            },
        ]
        selected = agentic_sdlc.select_github_review(reviews, "octocat")
        self.assertEqual(12, selected["id"])
        selected_at_commit = agentic_sdlc.select_github_review(reviews, "octocat", "aaa111")
        self.assertEqual(10, selected_at_commit["id"])

    def test_approve_from_github_pr_fetches_matching_review(self):
        self.init()
        authority_path = self.root / ".agentic-sdlc" / "authorities.json"
        authorities = json.loads(authority_path.read_text(encoding="utf-8"))
        authorities["product_owner"].update({
            "status": "assigned",
            "assignee": "github.com/octocat",
            "github_login": "octocat",
        })
        authority_path.write_text(json.dumps(authorities), encoding="utf-8")
        project_path = self.root / ".agentic-sdlc" / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["approval_sources"] = {"human_gate_default": "github-review", "allow_manual_fallback": False}
        project_path.write_text(json.dumps(project), encoding="utf-8")
        self.run_cli("plan", "--task-id", "GH-AUTO", "--task", "Capture product intent")
        path = self.root / ".agentic-sdlc" / "runs" / "GH-AUTO" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        gate = record["lifecycle_gates"][0]
        gate.update({
            "status": "ready",
            "artifact_bindings": [{"artifact_id": "A-1", "revision": "abc123", "digest": "sha256:1", "environment": None}],
            "preparers": [{"id": "intent-author", "role": "product-intent-agent", "kind": "agent"}],
            "independent_verifier": {"id": "reviewer", "role": "code-reviewer", "kind": "agent"},
            "independence_declaration": {"verifier_confirmed_not_preparer": True, "verifier_made_material_correction": False},
            "evidence_refs": [{"evidence_id": "E-1", "uri": "repo:evidence", "hash_algorithm": "sha256", "hash": "1", "classification": "internal"}],
        })
        path.write_text(json.dumps(record), encoding="utf-8")
        reviews_path = self.root / "reviews.json"
        reviews_path.write_text(json.dumps([
            {
                "id": 22,
                "state": "APPROVED",
                "submitted_at": "2030-01-02T00:00:00Z",
                "commit_id": "deadbeef",
                "user": {"login": "octocat"},
            }
        ]), encoding="utf-8")
        env = dict(os.environ)
        env["AGENTIC_SDLC_TEST_GITHUB_REVIEWS_FILE"] = str(reviews_path)
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "approve-from-github-pr",
                "--task-id",
                "GH-AUTO",
                "--gate",
                "G1",
                "--role",
                "product_owner",
                "--repo",
                "example/repo",
                "--pr",
                "12",
                "--root",
                str(self.root),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("approved", payload["gate_status"])
        self.assertEqual(22, payload["selected_review_id"])
        updated = json.loads(path.read_text(encoding="utf-8"))
        approval = updated["lifecycle_gates"][0]["human_approvals"][0]
        self.assertEqual("github-review:example/repo:pull/12:review/22:reviewer/octocat", approval["evidence_refs"][0]["uri"])

    @unittest.skipUnless(JSONSCHEMA_AVAILABLE, "full validation dependency is unavailable")
    def test_validate_rejects_truncated_dispatch(self):
        self.init()
        self.run_cli("plan", "--task-id", "BAD-DISPATCH", "--task", "Capture product intent")
        path = self.root / ".agentic-sdlc" / "runs" / "BAD-DISPATCH" / "dispatch-plan.json"
        path.write_text(json.dumps({"schema_version": 2, "agents": {"primary": [], "reviewers": []}}), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("dispatch-plan.json: schema" in error for error in result["errors"]))

    def test_validate_recomputes_dispatch_fingerprint(self):
        self.init()
        self.run_cli("plan", "--task-id", "BAD-FINGERPRINT", "--task", "Capture product intent")
        task_dir = self.root / ".agentic-sdlc" / "runs" / "BAD-FINGERPRINT"
        dispatch_path = task_dir / "dispatch-plan.json"
        record_path = task_dir / "run-record.json"
        dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        dispatch["inputs"]["task"] = "Deploy to production"
        record["scope"] = "Deploy to production"
        dispatch_path.write_text(json.dumps(dispatch), encoding="utf-8")
        record_path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("fingerprint does not match current dispatch content" in error for error in result["errors"]))

    def test_validate_rejects_prerequisite_bypass_and_wrong_reviewer(self):
        self.init()
        self.run_cli("plan", "--task-id", "BAD-1", "--task", "Create the service architecture")
        path = self.root / ".agentic-sdlc" / "runs" / "BAD-1" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        gate = record["lifecycle_gates"][4]
        gate.update({
            "status": "approved", "applicability": "applicable",
            "artifact_bindings": [{"artifact_id": "A-1", "revision": "1", "digest": "sha256:1", "environment": None}],
            "preparers": [{"id": "author", "role": "threat-modeler", "kind": "agent"}],
            "independent_verifier": {"id": "reviewer", "role": "code-reviewer", "kind": "agent"},
            "independence_declaration": {"verifier_confirmed_not_preparer": True, "verifier_made_material_correction": False},
            "authority_requirements": [
                {"authority_id": "security-reviewer", "authority_type": "independent-verifier", "role": "security-reviewer", "applicability": "applicable", "rationale": "required"},
                {"authority_id": "security_lead", "authority_type": "human-approver", "role": "Security Lead", "applicability": "applicable", "rationale": "required"},
                {"authority_id": "human_key_owner", "authority_type": "human-approver", "role": "Security Lead", "applicability": "applicable", "rationale": "relabel attempt"},
            ], "evidence_refs": [{"evidence_id": "E-1", "uri": "repo:evidence", "hash_algorithm": "sha256", "hash": "1", "classification": "internal"}],
            "human_approvals": [{"status": "approved", "approver": {"id": "lead", "role": "Security Lead", "kind": "human"}, "decided_at": "2030-01-01T00:00:00Z", "evidence_refs": [{"evidence_id": "AE-1", "uri": "repo:approval", "hash_algorithm": "sha256", "hash": "2", "classification": "internal"}]}],
        })
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("approved before all prerequisite gates" in error for error in result["errors"]))
        self.assertTrue(any("lacks required reviewer role" in error for error in result["errors"]))
        self.assertTrue(any("authority human_key_owner is relabeled" in error for error in result["errors"]))

    def test_validate_rejects_self_approval_and_invalid_exception(self):
        self.init()
        self.run_cli("plan", "--task-id", "BAD-2", "--task", "Capture product intent")
        path = self.root / ".agentic-sdlc" / "runs" / "BAD-2" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        gate = record["lifecycle_gates"][0]
        evidence = {"evidence_id": "E-1", "uri": "repo:evidence", "hash_algorithm": "sha256", "hash": "1", "classification": "internal"}
        gate.update({
            "status": "approved", "artifact_bindings": [{"artifact_id": "A-1", "revision": "1", "digest": "sha256:1", "environment": None}],
            "preparers": [{"id": "same", "role": "Product Intent Agent", "kind": "agent"}],
            "independent_verifier": {"id": "verifier", "role": "independent-reviewer", "kind": "agent"},
            "independence_declaration": {"verifier_confirmed_not_preparer": True, "verifier_made_material_correction": False},
            "authority_requirements": [], "evidence_refs": [evidence],
            "human_approvals": [{"status": "approved", "approver": {"id": "same", "role": "Product Owner", "kind": "human"}, "decided_at": "2030-01-01T00:00:00Z", "evidence_refs": [evidence]}],
            "findings": [{"finding_id": "F-1", "severity": "high", "status": "accepted-exception", "owner": "owner"}],
            "exceptions": [{"exception_id": "X-1", "finding_id": "F-1", "justification": "temporary", "compensating_controls": [], "owner": {"id": "owner", "role": "Owner", "kind": "human"}, "approver": {"id": "owner", "role": "Owner", "kind": "human"}, "expires_at": "2020-01-01T00:00:00Z", "remediation_plan": "fix"}],
        })
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("approver is not independent" in error for error in result["errors"]))
        self.assertTrue(any("lacks a valid exception" in error for error in result["errors"]))

    def test_validate_rejects_incomplete_downstream_invalidation(self):
        self.init()
        self.run_cli("plan", "--task-id", "BAD-3", "--task", "Create the service architecture")
        self.run_cli("invalidate", "--task-id", "BAD-3", "--earliest-gate", "G3", "--reason", "material change", "--actor", "system-architect")
        path = self.root / ".agentic-sdlc" / "runs" / "BAD-3" / "run-record.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["lifecycle_gates"][6]["status"] = "pending"
        path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("validate", expected=1)
        self.assertTrue(any("downstream gate G7 must be invalidated" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
