"""Repository health checks for the agent suite itself."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ROOT.parent


class RepositoryHealthTests(unittest.TestCase):
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
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "SAMPLE-001" in text or "sample-001" in text or "Sample-001" in text:
                offenders.append(normalized)

        self.assertEqual(offenders, [])

    def test_secure_cloud_agents_plugin_is_generated_and_in_sync(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_global_plugin.py"
        result = subprocess.run(
            ["python3", str(generator)],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        diff = subprocess.run(
            ["git", "diff", "--exit-code", "--stat", "--", "plugins/secure-cloud-agents"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(
            0,
            diff.returncode,
            "plugins/secure-cloud-agents is stale; run "
            "agents/orchestration/src/generate_global_plugin.py and commit the result:\n" + diff.stdout,
        )

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
                pointer = plugin_root / "skills" / skill_name / "SKILL.md"
                self.assertTrue(pointer.is_file(), str(pointer))
                self.assertIn(f"name: {skill_name}", pointer.read_text(encoding="utf-8"))

    def test_bin_agents_wrapper_is_executable(self) -> None:
        wrapper = REPOSITORY_ROOT / "bin" / "agents"
        self.assertTrue(wrapper.is_file(), str(wrapper))
        self.assertTrue(os.access(wrapper, os.X_OK), f"{wrapper} is not executable")

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
