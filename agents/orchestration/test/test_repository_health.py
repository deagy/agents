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
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ROOT.parent

# Single source of truth for this repository's current role count. Cross-
# checked directly against the AGENT.md files on disk below, so a role
# add/remove without updating this constant fails immediately instead of
# leaving the other assertions below silently pinned to a stale number.
EXPECTED_ROLE_COUNT = 49


class RepositoryHealthTests(unittest.TestCase):
    @staticmethod
    def _require_agentic_sdlc() -> None:
        if os.environ.get("AGENTIC_SDLC_BIN") or shutil.which("agentic-sdlc"):
            return
        raise unittest.SkipTest("Agentic SDLC executable is not configured")

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

        self.assertEqual(EXPECTED_ROLE_COUNT, len(metadata))
        self.assertEqual(EXPECTED_ROLE_COUNT, len(list(ROOT.rglob("AGENT.md"))))
        allowed = {"read_only", "document_author", "code_author", "test_author", "environment_operator"}
        for agent_id, values in metadata.items():
            with self.subTest(agent=agent_id):
                self.assertIn(values.get("capability"), allowed)
                if values.get("definition", "").startswith("authority/"):
                    # Authority aides prepare a human decision package and
                    # must never author/mutate the artifacts they report on;
                    # document_author here would violate their own
                    # independence clause (docs/proposals/human-authority-
                    # role-agents.md §8.2).
                    self.assertEqual("read_only", values["capability"])
                if values.get("definition", "").startswith("review/"):
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

    def test_hand_maintained_skill_count_matches_agents_skills(self) -> None:
        """Pins the hand-typed "N skills" prose in README.md/RUNBOOK.md to the
        actual `.agents/skills/` count, so a skill add/remove can't silently
        leave stale prose behind (as happened when it drifted to "6 skills"
        with 7 actually present).
        """
        skills_root = REPOSITORY_ROOT / ".agents" / "skills"
        actual_count = len(list(skills_root.glob("*/SKILL.md")))
        for doc_path in (REPOSITORY_ROOT / "README.md", REPOSITORY_ROOT / "agents" / "RUNBOOK.md"):
            text = doc_path.read_text(encoding="utf-8")
            self.assertIn(
                f"{actual_count} skills",
                text,
                f"{doc_path} does not say '{actual_count} skills' (actual count under {skills_root})",
            )

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

    def test_clinerules_pointer_is_tracked_and_points_at_canonical_sources(self) -> None:
        pointer_file = REPOSITORY_ROOT / ".clinerules" / "agents-repository.md"
        self.assertTrue(pointer_file.is_file(), str(pointer_file))

        content = pointer_file.read_text(encoding="utf-8")
        self.assertIn("AGENTS.md", content)
        self.assertIn("agents/RUNBOOK.md", content)

        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(pointer_file.relative_to(REPOSITORY_ROOT))],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(tracked.returncode, 0, tracked.stderr)

        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(pointer_file.parent.relative_to(REPOSITORY_ROOT))],
            cwd=REPOSITORY_ROOT,
            check=False,
        )
        self.assertNotEqual(ignored.returncode, 0, f"{pointer_file.parent} is ignored")

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

    def test_authority_aide_agents_are_generated_and_in_sync(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_authority_aides.py"
        checked = subprocess.run(
            ["python3", str(generator), "--check"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, checked.returncode, checked.stderr)

    def test_role_metadata_files_are_generated_and_in_sync(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_role_metadata.py"
        checked = subprocess.run(
            ["python3", str(generator), "--check"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, checked.returncode, checked.stderr)

    def test_secure_cloud_agents_plugin_is_generated_and_in_sync(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_global_plugin.py"
        with tempfile.TemporaryDirectory(prefix="agents-health-") as temporary_directory:
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

    def test_committed_plugin_matches_generator_output(self) -> None:
        """Guards against drift between catalog/agents/.agents/skills and the
        committed `plugins/cadre/` distribution. The sibling
        `test_secure_cloud_agents_plugin_is_generated_and_in_sync` only checks
        the generator against its own isolated `--output`, so it stays green
        even when the committed package has drifted; this test is the one
        that actually exercises the default (no `--output`) target, matching
        what `AGENTS.md`/`CLAUDE.md` document and what CI's
        `./bin/cadre generate-plugin --check` runs.
        """
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_global_plugin.py"
        checked = subprocess.run(
            ["python3", str(generator), "--check"],
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
            / "cadre"
            / "suite"
            / "agents"
            / "orchestration"
            / "src"
            / "migrate_execution_summary.py"
        )
        self.assertFalse(source_path.exists(), str(source_path))
        self.assertFalse(packaged_path.exists(), str(packaged_path))

    def test_packaged_runtime_has_no_removed_lifecycle_paths(self) -> None:
        plugin_root = REPOSITORY_ROOT / "plugins" / "cadre"
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

        plugin_root = REPOSITORY_ROOT / "plugins" / "cadre"
        for agent_id in catalog_agents:
            with self.subTest(agent=agent_id):
                md_path = plugin_root / "agents" / f"{agent_id}.md"
                codex_id = f"agents-{agent_id}"
                toml_path = plugin_root / "codex-agents" / f"{codex_id}.toml"
                self.assertTrue(md_path.is_file(), str(md_path))
                self.assertTrue(toml_path.is_file(), str(toml_path))
                self.assertIn(f"name: {agent_id}", md_path.read_text(encoding="utf-8"))
                self.assertIn(f'name = "{codex_id}"', toml_path.read_text(encoding="utf-8"))

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

        export_path = REPOSITORY_ROOT / "plugins" / "cadre" / "agent-catalog.json"
        export = json.loads(export_path.read_text(encoding="utf-8"))["agents"]
        self.assertEqual(set(catalog_agents), set(export))
        for agent_id, metadata in export.items():
            with self.subTest(agent=agent_id):
                self.assertIn(metadata["kind"], {"author", "reviewer", "specialist"})
                self.assertTrue(metadata["phase"])
                self.assertTrue((export_path.parent / metadata["definition"]).is_file(), metadata["definition"])

    def test_generated_wrappers_enforce_catalog_capabilities_and_provenance(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_global_plugin.py"
        with tempfile.TemporaryDirectory(prefix="agents-capabilities-") as temporary_directory:
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
            for agent_id in ("code-reviewer", "security-reviewer"):
                markdown = (plugin_root / "agents" / f"{agent_id}.md").read_text(encoding="utf-8")
                toml = (plugin_root / "codex-agents" / f"agents-{agent_id}.toml").read_text(encoding="utf-8")
                self.assertIn("tools: Read, Grep, Glob", markdown)
                self.assertNotIn("tools: Read, Grep, Glob, Bash", markdown)
                self.assertIn('sandbox_mode = "read-only"', toml)
                self.assertIn("generated: true", markdown)
                self.assertIn("canonical_source:", markdown)
                self.assertIn("# GENERATED FILE:", toml)
            for agent_id in ("application-engineer", "test-engineer"):
                author = (plugin_root / "agents" / f"{agent_id}.md").read_text(encoding="utf-8")
                self.assertIn("tools: Read, Grep, Glob, Bash, Edit, Write", author)
                self.assertIn('sandbox_mode = "workspace-write"', (plugin_root / "codex-agents" / f"agents-{agent_id}.toml").read_text(encoding="utf-8"))

    def test_plugin_advertised_role_count_matches_generated_catalog(self) -> None:
        plugin_root = REPOSITORY_ROOT / "plugins" / "cadre"
        catalog_count = len(
            json.loads((plugin_root / "agent-catalog.json").read_text(encoding="utf-8"))["agents"]
        )
        self.assertEqual(EXPECTED_ROLE_COUNT, catalog_count)
        for manifest in (
            plugin_root / ".codex-plugin" / "plugin.json",
            plugin_root / ".claude-plugin" / "plugin.json",
        ):
            content = manifest.read_text(encoding="utf-8")
            advertised = {int(value) for value in re.findall(r"(\d+) specialist roles", content)}
            self.assertEqual({catalog_count}, advertised, str(manifest))
        self.assertEqual(
            catalog_count,
            len(list((plugin_root / "codex-agents").glob("agents-*.toml"))),
        )

    def test_repository_profile_and_local_override_policy_stay_current(self) -> None:
        profile = (ROOT / "shared" / "team-profile.yaml").read_text(encoding="utf-8")
        self.assertIn(
            "source_control:\n  platform: github\n  change_model: pull_request",
            profile,
        )

        for local_root in (
            REPOSITORY_ROOT / ".claude" / "agents",
            REPOSITORY_ROOT / ".codex" / "agents",
        ):
            self.assertFalse(
                any(local_root.glob("*.md")) or any(local_root.glob("*.toml")),
                f"stale project-local agent overrides remain under {local_root}",
            )

        secure_cloud = json.loads(
            (
                REPOSITORY_ROOT
                / "plugins"
                / "cadre"
                / "profiles"
                / "secure-cloud"
                / "profile.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(19, len(secure_cloud["agents"]))
        catalog = json.loads(
            (
                REPOSITORY_ROOT
                / "plugins"
                / "cadre"
                / "agent-catalog.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(EXPECTED_ROLE_COUNT, len(catalog["agents"]))

    def test_packaged_plugin_manifests_declare_a_matching_semver_version(self) -> None:
        sys.path.insert(0, str(ROOT / "orchestration" / "src"))
        try:
            import plugin_version
        finally:
            sys.path.pop(0)

        self.assertEqual([], plugin_version.check_versions())
        versions = plugin_version.read_versions()
        self.assertRegex(versions["claude"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(versions["claude"], versions["codex"])

    def test_plugin_version_set_writes_both_manifests_or_neither(self) -> None:
        sys.path.insert(0, str(ROOT / "orchestration" / "src"))
        try:
            import plugin_version
        finally:
            sys.path.pop(0)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            claude_manifest = temporary / "claude.json"
            codex_manifest = temporary / "codex.json"
            claude_manifest.write_text('{\n  "name": "x",\n  "version": "0.1.0"\n}\n', encoding="utf-8")
            codex_manifest.write_text('{\n  "name": "x",\n  "version": "0.1.0"\n}\n', encoding="utf-8")

            with mock.patch.object(
                plugin_version,
                "MANIFESTS",
                {"claude": claude_manifest, "codex": codex_manifest},
            ):
                plugin_version.set_version("0.2.0")
                self.assertEqual("0.2.0", plugin_version.read_versions()["claude"])
                self.assertEqual("0.2.0", plugin_version.read_versions()["codex"])

                # Corrupt only the second manifest so validation must fail partway
                # through; neither manifest should end up changed by the attempt.
                codex_manifest.write_text('{\n  "name": "x",\n  "ver_sion": "0.2.0"\n}\n', encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, 'could not locate a "version" line'):
                    plugin_version.set_version("0.3.0")
                self.assertEqual(
                    '{\n  "name": "x",\n  "version": "0.2.0"\n}\n',
                    claude_manifest.read_text(encoding="utf-8"),
                    "claude manifest must be untouched when the codex manifest fails validation",
                )
                self.assertEqual(
                    '{\n  "name": "x",\n  "ver_sion": "0.2.0"\n}\n',
                    codex_manifest.read_text(encoding="utf-8"),
                )

    def test_codex_bootstrap_preserves_bare_files_and_rejects_unowned_collision(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            generated = (
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n'
            )
            (source / "agents-code-reviewer.toml").write_text(generated, encoding="utf-8")
            bare = target / "code-reviewer.toml"
            bare.write_text("user-owned bare wrapper\n", encoding="utf-8")

            installed = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("Installed 1", installed.stdout)
            self.assertEqual("user-owned bare wrapper\n", bare.read_text(encoding="utf-8"))

            namespaced = target / "agents-code-reviewer.toml"
            namespaced.write_text("", encoding="utf-8")
            empty_rejected = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, empty_rejected.returncode)
            self.assertIn("Refusing to overwrite unowned", empty_rejected.stderr)
            self.assertEqual("", namespaced.read_text(encoding="utf-8"))

            namespaced.write_text("user-owned collision\n", encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Refusing to overwrite unowned", rejected.stderr)
            self.assertEqual("user-owned collision\n", namespaced.read_text(encoding="utf-8"))

    @unittest.skipIf(sys.platform == "win32", "POSIX symlink behavior is required")
    def test_codex_bootstrap_rejects_symlinked_wrappers(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            generated = (
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n'
            )
            real_source = source / "real.toml"
            real_source.write_text(generated, encoding="utf-8")
            symlinked_source = source / "agents-code-reviewer.toml"
            os.symlink(real_source, symlinked_source)

            source_rejected = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, source_rejected.returncode)
            self.assertIn("Refusing non-regular source wrapper", source_rejected.stderr)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            (source / "agents-code-reviewer.toml").write_text(generated, encoding="utf-8")
            real_destination = target / "real-destination.toml"
            real_destination.write_text("user-owned destination\n", encoding="utf-8")
            os.symlink(real_destination, target / "agents-code-reviewer.toml")

            destination_rejected = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, destination_rejected.returncode)
            self.assertIn("Refusing symlinked destination wrapper", destination_rejected.stderr)
            self.assertEqual("user-owned destination\n", real_destination.read_text(encoding="utf-8"))

    def test_codex_bootstrap_writes_role_index_with_resolved_paths_and_models(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            (source / "agents-code-reviewer.toml").write_text(
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n'
                'model = "gpt-5-mini"\n',
                encoding="utf-8",
            )
            (source / "agents-test-engineer.toml").write_text(
                "# GENERATED FILE: canonical source is agents/review/test-engineer/AGENT.md\n"
                'name = "agents-test-engineer"\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("Index installed", result.stdout)

            index_path = target / "agents-index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(1, index["schema_version"])
            self.assertEqual("# GENERATED FILE: canonical source is agents/", index["generated_marker"])
            self.assertEqual(
                {
                    "code-reviewer": {
                        "path": str((target / "agents-code-reviewer.toml").resolve()),
                        "model": "gpt-5-mini",
                    },
                    "test-engineer": {
                        "path": str((target / "agents-test-engineer.toml").resolve()),
                        "model": None,
                    },
                },
                index["roles"],
            )

    def test_codex_bootstrap_role_index_is_byte_identical_across_unchanged_reruns(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            (source / "agents-code-reviewer.toml").write_text(
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n'
                'model = "gpt-5-mini"\n',
                encoding="utf-8",
            )
            index_path = target / "agents-index.json"

            first = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("Index installed", first.stdout)
            first_bytes = index_path.read_bytes()

            second = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("Index unchanged", second.stdout)
            self.assertEqual(first_bytes, index_path.read_bytes())

    def test_codex_bootstrap_role_index_updates_when_source_model_changes(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            wrapper_source = source / "agents-code-reviewer.toml"
            wrapper_source.write_text(
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n'
                'model = "gpt-5-mini"\n',
                encoding="utf-8",
            )
            index_path = target / "agents-index.json"

            subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual("gpt-5-mini", json.loads(index_path.read_text(encoding="utf-8"))["roles"]["code-reviewer"]["model"])

            wrapper_source.write_text(
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n'
                'model = "gpt-5"\n',
                encoding="utf-8",
            )
            updated = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("Index installed", updated.stdout)
            self.assertEqual("gpt-5", json.loads(index_path.read_text(encoding="utf-8"))["roles"]["code-reviewer"]["model"])

    def test_codex_bootstrap_role_index_rejects_unowned_collision(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            (source / "agents-code-reviewer.toml").write_text(
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n',
                encoding="utf-8",
            )
            index_path = target / "agents-index.json"
            index_path.write_text('{"unowned": true}', encoding="utf-8")

            rejected = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Refusing to overwrite unowned", rejected.stderr)
            self.assertEqual('{"unowned": true}', index_path.read_text(encoding="utf-8"))

    @unittest.skipIf(sys.platform == "win32", "POSIX symlink behavior is required")
    def test_codex_bootstrap_rejects_symlinked_role_index(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            (source / "agents-code-reviewer.toml").write_text(
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n',
                encoding="utf-8",
            )
            real_destination = target / "real-index.json"
            real_destination.write_text("user-owned index\n", encoding="utf-8")
            os.symlink(real_destination, target / "agents-index.json")

            rejected = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Refusing symlinked destination wrapper", rejected.stderr)
            self.assertEqual("user-owned index\n", real_destination.read_text(encoding="utf-8"))

    def test_codex_bootstrap_role_index_left_unchanged_when_a_wrapper_write_fails(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            # "code-reviewer" sorts before "test-engineer", so the loop writes
            # it successfully before reaching the collision below.
            (source / "agents-code-reviewer.toml").write_text(
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n',
                encoding="utf-8",
            )
            (source / "agents-test-engineer.toml").write_text(
                "# GENERATED FILE: canonical source is agents/review/test-engineer/AGENT.md\n"
                'name = "agents-test-engineer"\n',
                encoding="utf-8",
            )
            index_path = target / "agents-index.json"

            # First run: no collision yet, establishes an installed index.
            first = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("Index installed", first.stdout)
            established_index_bytes = index_path.read_bytes()

            # Corrupt one of the already-installed namespaced wrappers so the
            # next run fails partway through the per-wrapper loop, before the
            # index would be rebuilt.
            (target / "agents-test-engineer.toml").write_text(
                "user-owned collision\n", encoding="utf-8",
            )
            failing = subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, failing.returncode)
            self.assertIn("Refusing to overwrite unowned", failing.stderr)
            self.assertTrue(
                (target / "agents-code-reviewer.toml").read_text(encoding="utf-8").startswith(
                    "# GENERATED FILE:"
                ),
                "the wrapper preceding the collision should still have been written",
            )
            self.assertEqual(
                established_index_bytes,
                index_path.read_bytes(),
                "the index must not change when a wrapper write fails mid-loop",
            )

    def test_codex_bootstrap_role_index_prunes_roles_removed_from_source(self) -> None:
        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "source"
            target = temporary / "home" / ".codex" / "agents"
            source.mkdir()
            target.mkdir(parents=True)
            code_reviewer_source = source / "agents-code-reviewer.toml"
            code_reviewer_source.write_text(
                "# GENERATED FILE: canonical source is agents/review/code-reviewer/AGENT.md\n"
                'name = "agents-code-reviewer"\n',
                encoding="utf-8",
            )
            (source / "agents-test-engineer.toml").write_text(
                "# GENERATED FILE: canonical source is agents/review/test-engineer/AGENT.md\n"
                'name = "agents-test-engineer"\n',
                encoding="utf-8",
            )
            index_path = target / "agents-index.json"

            subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            first_roles = json.loads(index_path.read_text(encoding="utf-8"))["roles"]
            self.assertEqual({"code-reviewer", "test-engineer"}, set(first_roles))

            code_reviewer_source.unlink()
            subprocess.run(
                [sys.executable, str(script), "--source", str(source), "--target", str(target)],
                check=True, capture_output=True, text=True,
            )
            second_roles = json.loads(index_path.read_text(encoding="utf-8"))["roles"]
            self.assertEqual({"test-engineer"}, set(second_roles))

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW support is required")
    def test_codex_bootstrap_no_follow_guards_run_at_open_time(self) -> None:
        import importlib.util

        script = ROOT / "orchestration" / "src" / "sync_codex_agents.py"
        spec = importlib.util.spec_from_file_location("sync_codex_agents_under_test", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source_target = temporary / "source-target.toml"
            source_target.write_text("source content\n", encoding="utf-8")
            source_link = temporary / "agents-source.toml"
            os.symlink(source_target, source_link)
            with self.assertRaises(OSError):
                module._read_regular_file(source_link)

            destination_target = temporary / "destination-target.toml"
            destination_target.write_text("destination content\n", encoding="utf-8")
            destination_link = temporary / "agents-destination.toml"
            os.symlink(destination_target, destination_link)
            with mock.patch.object(Path, "is_symlink", return_value=False):
                with self.assertRaises(OSError):
                    module._write_owned_wrapper(destination_link, b"new content\n")
            self.assertEqual("destination content\n", destination_target.read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform != "win32", "packaged wrapper is a POSIX sh script")
    def test_packaged_selector_targets_callers_git_repository(self) -> None:
        wrapper = REPOSITORY_ROOT / "plugins" / "cadre" / "bin" / "cadre"
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "unrelated"
            target.mkdir()
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Test"], check=True)
            (target / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "add", "."], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "base"], check=True)
            base = subprocess.run(
                ["git", "-C", str(target), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, encoding="utf-8",
            ).stdout.strip()
            (target / "frontend").mkdir()
            (target / "frontend" / "App.tsx").write_text("export default 1\n", encoding="utf-8")

            status = subprocess.run(
                [str(wrapper), "select", "--task", "Update React"],
                cwd=target, check=True, capture_output=True, text=True,
            )
            status_plan = json.loads(status.stdout)
            self.assertEqual(str(target.resolve()), status_plan["inputs"]["repository_root"])
            self.assertEqual(["frontend/App.tsx"], status_plan["inputs"]["changed_files"])

            subprocess.run(["git", "-C", str(target), "add", "."], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "frontend"], check=True)
            diff = subprocess.run(
                [str(wrapper), "select", "--task", "Update React", "--base", base],
                cwd=target, check=True, capture_output=True, text=True,
            )
            self.assertEqual(["frontend/App.tsx"], json.loads(diff.stdout)["inputs"]["changed_files"])

    def test_generated_package_has_no_source_paths_or_unsafe_relative_documentation_paths(self) -> None:
        generator = REPOSITORY_ROOT / "agents" / "orchestration" / "src" / "generate_global_plugin.py"
        with tempfile.TemporaryDirectory(prefix="agents-packaging-") as temporary_directory:
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
        plugin_root = REPOSITORY_ROOT / "plugins" / "cadre"
        provider = json.loads((plugin_root / "provider.json").read_text(encoding="utf-8"))
        self.assertEqual("cadre", provider["id"])
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

    @staticmethod
    def _semver_tuple(value: str) -> tuple[int, int, int]:
        # Verbatim copy of `semver_tuple` from `agentic-sdlc`'s
        # plugins/agentic-sdlc/scripts/agentic_sdlc.py (lines 84-88), in a
        # `deagy/agentic-sdlc` checkout. Reimplemented locally rather than imported because
        # `AGENTIC_SDLC_BIN`/`PATH` resolution does not guarantee an importable
        # layout for the standalone kernel script.
        match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", value)
        if not match:
            raise ValueError(f"invalid semantic version: {value}")
        return tuple(int(part) for part in match.groups())  # type: ignore[return-value]

    @classmethod
    def _kernel_version_in_range(cls, live: str, minimum: str, maximum_exclusive: str) -> bool:
        return cls._semver_tuple(minimum) <= cls._semver_tuple(live) < cls._semver_tuple(maximum_exclusive)

    def test_kernel_version_in_range_enforces_half_open_bounds(self) -> None:
        self.assertFalse(self._kernel_version_in_range("0.2.9", "0.3.0", "0.4.0"))
        self.assertTrue(self._kernel_version_in_range("0.3.0", "0.3.0", "0.4.0"))
        self.assertFalse(self._kernel_version_in_range("0.4.0", "0.3.0", "0.4.0"))
        self.assertTrue(self._kernel_version_in_range("0.3.9", "0.3.0", "0.4.0"))

    def test_secure_cloud_agents_provider_kernel_compatibility_covers_live_sdlc_version(self) -> None:
        self._require_agentic_sdlc()
        provider = json.loads(
            (REPOSITORY_ROOT / "plugins" / "cadre" / "provider.json").read_text(encoding="utf-8")
        )
        minimum = provider["kernel_compatibility"]["minimum"]
        maximum_exclusive = provider["kernel_compatibility"]["maximum_exclusive"]
        self.assertRegex(minimum, r"^\d+\.\d+\.\d+$")
        self.assertRegex(maximum_exclusive, r"^\d+\.\d+\.\d+$")

        result = subprocess.run(
            [str(REPOSITORY_ROOT / "bin" / "cadre"), "sdlc", "--version"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=os.environ.copy(),
        )
        live_version = result.stdout.strip()

        self.assertTrue(
            self._kernel_version_in_range(live_version, minimum, maximum_exclusive),
            f"live agentic-sdlc kernel version {live_version!r} is outside the "
            f"provider-declared range [{minimum}, {maximum_exclusive})",
        )

    def test_bin_agents_wrapper_is_executable(self) -> None:
        wrapper = REPOSITORY_ROOT / "bin" / "cadre"
        self.assertTrue(wrapper.is_file(), str(wrapper))
        self.assertTrue(os.access(wrapper, os.X_OK), f"{wrapper} is not executable")

    def test_bin_agents_delegates_sdlc_to_standalone_kernel(self) -> None:
        self._require_agentic_sdlc()
        result = subprocess.run(
            [str(REPOSITORY_ROOT / "bin" / "cadre"), "sdlc", "--version"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=os.environ.copy(),
        )
        self.assertEqual("0.3.0", result.stdout.strip())

    @unittest.skipUnless(sys.platform != "win32", "bin/cadre is a POSIX sh script")
    def test_bin_agents_wrapper_dispatches_select_matching_direct_invocation(self) -> None:
        self._require_agentic_sdlc()
        wrapper = REPOSITORY_ROOT / "bin" / "cadre"
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

    @unittest.skipUnless(sys.platform != "win32", "bin/cadre is a POSIX sh script")
    def test_bin_agents_wrapper_resolves_correctly_through_a_symlink(self) -> None:
        self._require_agentic_sdlc()
        wrapper = REPOSITORY_ROOT / "bin" / "cadre"
        with tempfile.TemporaryDirectory() as temporary_directory:
            link = Path(temporary_directory) / "agents"
            link.symlink_to(wrapper)
            result = subprocess.run(
                [
                    str(link), "select",
                    "--root", str(REPOSITORY_ROOT),
                    "--task", "Capture product intent",
                    "--files", "README.md",
                    "--classification", "internal",
                    "--task-id", "WRAPPER-HEALTH-2",
                ],
                cwd=temporary_directory,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual("ready", json.loads(result.stdout)["status"])

    @unittest.skipUnless(sys.platform != "win32", "bin/cadre is a POSIX sh script")
    def test_bin_agents_wrapper_rejects_unknown_subcommand(self) -> None:
        wrapper = REPOSITORY_ROOT / "bin" / "cadre"
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
        self._require_agentic_sdlc()
        wrapper = REPOSITORY_ROOT / "plugins" / "cadre" / "bin" / "cadre"
        self.assertTrue(wrapper.is_file(), str(wrapper))
        self.assertTrue(os.access(wrapper, os.X_OK), f"{wrapper} is not executable")
        selector = ROOT / "orchestration" / "src" / "select_agents.py"
        arguments = [
            "--root", str(REPOSITORY_ROOT),
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

        # bin/cadre.py owns table parsing, sdlc delegation, usage text, and
        # dispatch; the per-platform shims (bin/cadre, bin/cadre.ps1) only
        # find a Python interpreter and hand off to it, so this logic exists
        # exactly once instead of being duplicated per shell language.
        dispatcher_source = (REPOSITORY_ROOT / "bin" / "cadre.py").read_text(encoding="utf-8")
        self.assertIn("subcommands.tsv", dispatcher_source)

        sh_source = (REPOSITORY_ROOT / "bin" / "cadre").read_text(encoding="utf-8")
        ps1_source = (REPOSITORY_ROOT / "bin" / "cadre.ps1").read_text(encoding="utf-8")
        for source in (sh_source, ps1_source):
            self.assertNotIn("subcommands.tsv", source, "shims must not also parse the subcommand table")
            self.assertIn("cadre.py", source, "shims must hand off to the shared dispatcher")
            for _name, script, _description in rows:
                self.assertNotIn(script, source, "subcommand table must not also be hardcoded in the shim")

    def test_packaged_wrapper_covers_every_non_excluded_subcommand_table_entry(self) -> None:
        """Extends the `select`-only parity check above to every packaged
        subcommand: a bin/subcommands.tsv script-path change must show up in
        the packaged plugins/cadre/bin/cadre wrapper, not just for `select`.
        """
        sys.path.insert(0, str(ROOT / "orchestration" / "src"))
        try:
            import generate_global_plugin
        finally:
            sys.path.pop(0)

        rows = generate_global_plugin.packaged_subcommands(REPOSITORY_ROOT)
        self.assertTrue(rows)
        wrapper_source = (REPOSITORY_ROOT / "plugins" / "cadre" / "bin" / "cadre").read_text(encoding="utf-8")
        for name, script in rows:
            with self.subTest(subcommand=name):
                self.assertIn(name, wrapper_source)
                self.assertIn(script, wrapper_source)
        for excluded in generate_global_plugin.PACKAGED_SUBCOMMAND_EXCLUSIONS:
            with self.subTest(excluded=excluded):
                self.assertNotIn(f"{excluded})", wrapper_source)

    def _powershell_interpreter(self) -> str | None:
        return shutil.which("pwsh") or shutil.which("powershell")

    def test_bin_agents_ps1_wrapper_dispatches_select_matching_direct_invocation(self) -> None:
        interpreter = self._powershell_interpreter()
        if interpreter is None:
            self.skipTest("no PowerShell interpreter (pwsh/powershell) available")
        wrapper = REPOSITORY_ROOT / "bin" / "cadre.ps1"
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
        wrapper = REPOSITORY_ROOT / "bin" / "cadre.ps1"
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
