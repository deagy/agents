"""Repository health checks for the agent suite itself."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ROOT.parent


class RepositoryHealthTests(unittest.TestCase):
    def test_provider_repository_has_no_project_lifecycle_overlay(self) -> None:
        overlay = REPOSITORY_ROOT / ".agentic-sdlc"
        self.assertFalse(overlay.exists(), str(overlay))

    def test_catalog_definitions_and_agent_files_stay_in_sync(self) -> None:
        catalog_agents: dict[str, str] = {}
        current_agent: str | None = None
        for line in (ROOT / "catalog.yaml").read_text(encoding="utf-8").splitlines():
            if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
                current_agent = line.strip()[:-1]
            elif current_agent and line.strip().startswith("definition:"):
                catalog_agents[current_agent] = line.split(":", 1)[1].strip()

        agent_files = {
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in ROOT.rglob("AGENT.md")
        }
        self.assertEqual(set(catalog_agents.values()), agent_files)
        for relative_path in catalog_agents.values():
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_catalog_declares_capabilities_and_reviewers_are_read_only(self) -> None:
        catalog = (ROOT / "catalog.yaml").read_text(encoding="utf-8").splitlines()
        current_agent: str | None = None
        metadata: dict[str, dict[str, str]] = {}
        for line in catalog:
            if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
                current_agent = line.strip()[:-1]
                metadata[current_agent] = {}
            elif current_agent and line.strip().startswith(("definition:", "phase:", "capability:")):
                key, value = line.strip().split(":", 1)
                metadata[current_agent][key] = value.strip()

        self.assertEqual(34, len(metadata))
        allowed = {"read_only", "document_author", "code_author", "test_author", "environment_operator"}
        for agent_id, values in metadata.items():
            with self.subTest(agent=agent_id):
                self.assertIn(values.get("capability"), allowed)
                if values.get("definition", "").startswith("review/") or agent_id == "test-engineer":
                    self.assertEqual("read_only", values["capability"])

    def test_workflow_values_match_schema_and_files(self) -> None:
        schema = json.loads((ROOT / "orchestration" / "selection.schema.json").read_text(encoding="utf-8"))
        workflow_values = set(schema["properties"]["workflow"]["enum"])
        workflow_files = {
            path.stem
            for path in (ROOT / "workflows").glob("*.md")
        }
        self.assertEqual(workflow_values - {"needs-triage"}, workflow_files)

    def test_publishable_skill_folders_are_tracked_and_not_ignored(self) -> None:
        skills_root = REPOSITORY_ROOT / ".agents" / "skills"
        for skill_file in skills_root.glob("*/SKILL.md"):
            skill_dir = skill_file.parent
            openai_yaml = skill_dir / "agents" / "openai.yaml"
            self.assertTrue(openai_yaml.is_file(), str(openai_yaml))

            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(skill_file.relative_to(REPOSITORY_ROOT))],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(tracked.returncode, 0, tracked.stderr)

            ignored = subprocess.run(
                ["git", "check-ignore", "-q", str(skill_dir.relative_to(REPOSITORY_ROOT))],
                cwd=REPOSITORY_ROOT,
                check=False,
            )
            self.assertNotEqual(ignored.returncode, 0, f"{skill_dir} is ignored")

    def test_claude_skill_pointers_match_the_canonical_codex_skill(self) -> None:
        skills_root = REPOSITORY_ROOT / ".agents" / "skills"
        claude_skills_root = REPOSITORY_ROOT / ".claude" / "skills"
        for skill_file in skills_root.glob("*/SKILL.md"):
            skill_name = skill_file.parent.name
            with self.subTest(skill=skill_name):
                pointer_file = claude_skills_root / skill_name / "SKILL.md"
                self.assertTrue(pointer_file.is_file(), str(pointer_file))

                def frontmatter(path: Path) -> dict[str, str]:
                    content = path.read_text(encoding="utf-8")
                    block = content.split("---", 2)[1]
                    return dict(
                        (part.strip() for part in line.split(":", 1))
                        for line in block.splitlines()
                        if line.strip()
                    )

                canonical = frontmatter(skill_file)
                pointer = frontmatter(pointer_file)
                self.assertEqual(canonical["name"], pointer["name"])
                self.assertEqual(canonical["description"], pointer["description"])
                self.assertIn(
                    f".agents/skills/{skill_name}/SKILL.md",
                    pointer_file.read_text(encoding="utf-8"),
                )

                tracked = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", str(pointer_file.relative_to(REPOSITORY_ROOT))],
                    cwd=REPOSITORY_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                self.assertEqual(tracked.returncode, 0, tracked.stderr)

    def test_sample_references_are_limited_to_allowed_archives(self) -> None:
        allowed_prefixes = (
            ".gitignore",
            "agents/orchestration/examples/SAMPLE-001",
            "agents/orchestration/examples/SAMPLE-001-report.md",
            "agents/orchestration/examples/sample-plan.json",
            "agents/orchestration/runs/.gitignore",
            "agents/orchestration/runs/SAMPLE-001-IMPLEMENT",
            "agents/orchestration/test/test_repository_health.py",
            "agents/orchestration/test/test_run_record_validation.py",
            "sample-001/",
        )
        tracked_files = subprocess.run(
            ["git", "ls-files"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()

        offenders: list[str] = []
        for relative_path in tracked_files:
            normalized = relative_path.replace("\\", "/")
            if normalized.startswith(allowed_prefixes):
                continue
            path = REPOSITORY_ROOT / normalized
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "SAMPLE-001" in text or "sample-001" in text or "Sample-001" in text:
                offenders.append(normalized)

        self.assertEqual(offenders, [])

    def test_secure_cloud_agents_plugin_is_generated_and_in_sync(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_global_plugin.py"
        with tempfile.TemporaryDirectory(prefix="secure-cloud-agents-health-") as temporary_directory:
            output = Path(temporary_directory) / "plugin"
            generated = subprocess.run(
                ["python3", str(generator), "--output", str(output)],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            checked = subprocess.run(
                ["python3", str(generator), "--check", "--output", str(output)],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)

    def test_removed_lifecycle_migration_utility_cannot_ship(self) -> None:
        source_path = ROOT / "orchestration" / "src" / "migrate_execution_summary.py"
        packaged_path = (
            REPOSITORY_ROOT
            / "plugins"
            / "secure-cloud-agents"
            / "suite"
            / "agents"
            / "orchestration"
            / "src"
            / "migrate_execution_summary.py"
        )
        self.assertFalse(source_path.exists(), str(source_path))
        self.assertFalse(packaged_path.exists(), str(packaged_path))

    def test_packaged_runtime_has_no_removed_lifecycle_paths(self) -> None:
        plugin_root = REPOSITORY_ROOT / "plugins" / "secure-cloud-agents"
        offenders: list[str] = []
        for path in plugin_root.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            if "plugins/agentic-sdlc" in content or "migrate_execution_summary" in content:
                offenders.append(str(path.relative_to(plugin_root)))
        self.assertEqual([], offenders)

    def test_suite_does_not_duplicate_lifecycle_authority(self) -> None:
        forbidden = [
            ROOT / "orchestration" / "quality-gates.md",
            ROOT / "orchestration" / "run-record.schema.json",
            ROOT / "orchestration" / "src" / "validate_run_record.py",
            ROOT / "orchestration" / "agentic-sdlc-artifact-contract.md",
            REPOSITORY_ROOT / ".agentic-sdlc",
        ]
        for path in forbidden:
            with self.subTest(path=path):
                self.assertFalse(path.exists(), str(path))

    def test_secure_cloud_agents_plugin_covers_every_catalog_agent_and_skill(self) -> None:
        catalog_agents: dict[str, str] = {}
        current_agent: str | None = None
        for line in (ROOT / "catalog.yaml").read_text(encoding="utf-8").splitlines():
            if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
                current_agent = line.strip()[:-1]
                catalog_agents[current_agent] = ""

        plugin_root = REPOSITORY_ROOT / "plugins" / "secure-cloud-agents"
        for agent_id in catalog_agents:
            with self.subTest(agent=agent_id):
                md_path = plugin_root / "agents" / f"{agent_id}.md"
                toml_path = plugin_root / "codex-agents" / f"{agent_id}.toml"
                self.assertTrue(md_path.is_file(), str(md_path))
                self.assertTrue(toml_path.is_file(), str(toml_path))
                self.assertIn(f"name: {agent_id}", md_path.read_text(encoding="utf-8"))
                self.assertIn(f'name = "{agent_id}"', toml_path.read_text(encoding="utf-8"))

        skills_root = REPOSITORY_ROOT / ".agents" / "skills"
        for skill_file in skills_root.glob("*/SKILL.md"):
            skill_name = skill_file.parent.name
            with self.subTest(skill=skill_name):
                packaged_skill = plugin_root / "skills" / skill_name / "SKILL.md"
                self.assertTrue(packaged_skill.is_file(), str(packaged_skill))
                self.assertIn(f"name: {skill_name}", packaged_skill.read_text(encoding="utf-8"))

    def test_secure_cloud_agents_agent_catalog_export_covers_every_role(self) -> None:
        catalog_agents: dict[str, str] = {}
        current_agent: str | None = None
        for line in (ROOT / "catalog.yaml").read_text(encoding="utf-8").splitlines():
            if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
                current_agent = line.strip()[:-1]
                catalog_agents[current_agent] = ""

        export_path = REPOSITORY_ROOT / "plugins" / "secure-cloud-agents" / "agent-catalog.json"
        export = json.loads(export_path.read_text(encoding="utf-8"))["agents"]
        self.assertEqual(set(catalog_agents), set(export))
        for agent_id, metadata in export.items():
            with self.subTest(agent=agent_id):
                self.assertIn(metadata["kind"], {"author", "reviewer", "specialist"})
                self.assertTrue(metadata["phase"])
                self.assertTrue((export_path.parent / metadata["definition"]).is_file(), metadata["definition"])

    def test_generated_wrappers_enforce_catalog_capabilities_and_provenance(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_global_plugin.py"
        with tempfile.TemporaryDirectory(prefix="secure-cloud-agents-capabilities-") as temporary_directory:
            plugin_root = Path(temporary_directory) / "plugin"
            result = subprocess.run(
                ["python3", str(generator), "--output", str(plugin_root)],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, result.returncode)
            for agent_id in ("code-reviewer", "security-reviewer", "test-engineer"):
                markdown = (plugin_root / "agents" / f"{agent_id}.md").read_text(encoding="utf-8")
                toml = (plugin_root / "codex-agents" / f"{agent_id}.toml").read_text(encoding="utf-8")
                self.assertIn("tools: Read, Grep, Glob", markdown)
                self.assertNotIn("tools: Read, Grep, Glob, Bash", markdown)
                self.assertIn('sandbox_mode = "read-only"', toml)
                self.assertIn("generated: true", markdown)
                self.assertIn("canonical_source:", markdown)
                self.assertIn("# GENERATED FILE:", toml)
            author = (plugin_root / "agents" / "application-engineer.md").read_text(encoding="utf-8")
            self.assertIn("tools: Read, Grep, Glob, Bash, Edit, Write", author)
            self.assertIn('sandbox_mode = "workspace-write"', (plugin_root / "codex-agents" / "application-engineer.toml").read_text(encoding="utf-8"))

    def test_generated_package_has_no_source_paths_or_unsafe_relative_documentation_paths(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_global_plugin.py"
        with tempfile.TemporaryDirectory(prefix="secure-cloud-agents-packaging-") as temporary_directory:
            plugin_root = Path(temporary_directory) / "plugin"
            subprocess.run(
                ["python3", str(generator), "--output", str(plugin_root)],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            for path in plugin_root.rglob("*"):
                if not path.is_file():
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn(str(REPOSITORY_ROOT), content, str(path))
            for path in (plugin_root / "suite" / "agents").rglob("*.md"):
                content = path.read_text(encoding="utf-8")
                for raw_relative in re.findall(r"(?<!https:)(?<!https://)(\.\./[^\s`)'\"]+)", content):
                    relative = raw_relative.rstrip(".,")
                    target = (path.parent / relative).resolve()
                    self.assertTrue(target.is_file() or target.is_dir(), f"{path}: {relative}")

    def test_secure_cloud_agents_plugin_is_self_contained(self) -> None:
        plugin_root = REPOSITORY_ROOT / "plugins" / "secure-cloud-agents"
        provider = json.loads((plugin_root / "provider.json").read_text(encoding="utf-8"))
        self.assertEqual("secure-cloud-agents", provider["id"])
        self.assertEqual("0.3.0", provider["version"])
        self.assertTrue((plugin_root / "suite" / "agents" / "catalog.yaml").is_file())
        offenders = []
        for path in plugin_root.rglob("*"):
            if (
                path.is_file()
                and path.suffix not in {".pyc", ".pyo"}
                and "__pycache__" not in path.parts
                and str(REPOSITORY_ROOT) in path.read_text(encoding="utf-8", errors="ignore")
            ):
                offenders.append(str(path.relative_to(plugin_root)))
        self.assertEqual([], offenders)

    def test_bin_agents_wrapper_is_executable(self) -> None:
        wrapper = REPOSITORY_ROOT / "bin" / "agents"
        self.assertTrue(wrapper.is_file(), str(wrapper))
        self.assertTrue(os.access(wrapper, os.X_OK), f"{wrapper} is not executable")

    def test_bin_agents_delegates_sdlc_to_standalone_kernel(self) -> None:
        executable = os.environ.get("AGENTIC_SDLC_BIN")
        if not executable:
            self.skipTest("AGENTIC_SDLC_BIN is not configured")
        result = subprocess.run(
            [str(REPOSITORY_ROOT / "bin" / "agents"), "sdlc", "--version"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=os.environ.copy(),
        )
        self.assertEqual("0.3.0", result.stdout.strip())

    @unittest.skipUnless(sys.platform != "win32", "bin/agents is a POSIX sh script")
    def test_bin_agents_wrapper_dispatches_select_matching_direct_invocation(self) -> None:
        wrapper = REPOSITORY_ROOT / "bin" / "agents"
        selector = ROOT / "orchestration" / "src" / "select_agents.py"
        arguments = [
            "--task", "Update the React navigation",
            "--files", "frontend/src/Nav.tsx",
            "--classification", "internal",
            "--task-id", "WRAPPER-HEALTH-1",
        ]
        direct = subprocess.run(
            [sys.executable, str(selector), *arguments],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        via_wrapper = subprocess.run(
            [str(wrapper), "select", *arguments],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        direct_payload = json.loads(direct.stdout)
        wrapper_payload = json.loads(via_wrapper.stdout)
        direct_payload.pop("generated_at", None)
        wrapper_payload.pop("generated_at", None)
        self.assertEqual(direct_payload, wrapper_payload)

    @unittest.skipUnless(sys.platform != "win32", "bin/agents is a POSIX sh script")
    def test_bin_agents_wrapper_resolves_correctly_through_a_symlink(self) -> None:
        wrapper = REPOSITORY_ROOT / "bin" / "agents"
        with tempfile.TemporaryDirectory() as temporary_directory:
            link = Path(temporary_directory) / "agents"
            link.symlink_to(wrapper)
            result = subprocess.run(
                [str(link), "select", "--task", "Capture product intent", "--classification", "internal", "--task-id", "WRAPPER-HEALTH-2"],
                cwd=temporary_directory,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual("ready", json.loads(result.stdout)["status"])

    @unittest.skipUnless(sys.platform != "win32", "bin/agents is a POSIX sh script")
    def test_bin_agents_wrapper_rejects_unknown_subcommand(self) -> None:
        wrapper = REPOSITORY_ROOT / "bin" / "agents"
        result = subprocess.run(
            [str(wrapper), "not-a-real-subcommand"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unknown subcommand", result.stderr)

    def test_secure_cloud_agents_plugin_bin_wrapper_matches_direct_invocation(self) -> None:
        wrapper = REPOSITORY_ROOT / "plugins" / "secure-cloud-agents" / "bin" / "agents"
        self.assertTrue(wrapper.is_file(), str(wrapper))
        self.assertTrue(os.access(wrapper, os.X_OK), f"{wrapper} is not executable")
        selector = ROOT / "orchestration" / "src" / "select_agents.py"
        arguments = [
            "--task", "Update the React navigation",
            "--files", "frontend/src/Nav.tsx",
            "--classification", "internal",
            "--task-id", "WRAPPER-HEALTH-4",
        ]
        direct = subprocess.run(
            [sys.executable, str(selector), *arguments],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            via_plugin_wrapper = subprocess.run(
                [str(wrapper), "select", *arguments],
                cwd=temporary_directory,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        direct_payload = json.loads(direct.stdout)
        wrapper_payload = json.loads(via_plugin_wrapper.stdout)
        direct_payload.pop("generated_at", None)
        wrapper_payload.pop("generated_at", None)
        for payload in (direct_payload, wrapper_payload):
            payload.pop("dispatch_fingerprint", None)
            for request in payload.get("knowledge_context", {}).get("requests", []):
                request["invocation"]["args"][0] = "<packaged-knowledge-cli>"
        self.assertEqual(direct_payload, wrapper_payload)

    def test_bin_agents_subcommand_table_is_the_single_source_of_truth(self) -> None:
        table = REPOSITORY_ROOT / "bin" / "subcommands.tsv"
        self.assertTrue(table.is_file(), str(table))
        rows = [line.split("\t") for line in table.read_text(encoding="utf-8").splitlines() if line]
        self.assertTrue(rows)
        for name, script, description in rows:
            with self.subTest(subcommand=name):
                self.assertTrue((REPOSITORY_ROOT / script).is_file(), script)
                self.assertTrue(description)
        sh_source = (REPOSITORY_ROOT / "bin" / "agents").read_text(encoding="utf-8")
        ps1_source = (REPOSITORY_ROOT / "bin" / "agents.ps1").read_text(encoding="utf-8")
        for source in (sh_source, ps1_source):
            self.assertIn("subcommands.tsv", source)
            for _name, script, _description in rows:
                self.assertNotIn(script, source, "subcommand table must not also be hardcoded in the wrapper")

    def _powershell_interpreter(self) -> str | None:
        return shutil.which("pwsh") or shutil.which("powershell")

    def test_bin_agents_ps1_wrapper_dispatches_select_matching_direct_invocation(self) -> None:
        interpreter = self._powershell_interpreter()
        if interpreter is None:
            self.skipTest("no PowerShell interpreter (pwsh/powershell) available")
        wrapper = REPOSITORY_ROOT / "bin" / "agents.ps1"
        selector = ROOT / "orchestration" / "src" / "select_agents.py"
        arguments = [
            "--task", "Update the React navigation",
            "--files", "frontend/src/Nav.tsx",
            "--classification", "internal",
            "--task-id", "WRAPPER-HEALTH-3",
        ]
        direct = subprocess.run(
            [sys.executable, str(selector), *arguments],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        via_wrapper = subprocess.run(
            [interpreter, "-File", str(wrapper), "select", *arguments],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        direct_payload = json.loads(direct.stdout)
        wrapper_payload = json.loads(via_wrapper.stdout)
        direct_payload.pop("generated_at", None)
        wrapper_payload.pop("generated_at", None)
        self.assertEqual(direct_payload, wrapper_payload)

    def test_bin_agents_ps1_wrapper_rejects_unknown_subcommand(self) -> None:
        interpreter = self._powershell_interpreter()
        if interpreter is None:
            self.skipTest("no PowerShell interpreter (pwsh/powershell) available")
        wrapper = REPOSITORY_ROOT / "bin" / "agents.ps1"
        result = subprocess.run(
            [interpreter, "-File", str(wrapper), "not-a-real-subcommand"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unknown subcommand", result.stderr)


if __name__ == "__main__":
    unittest.main()
