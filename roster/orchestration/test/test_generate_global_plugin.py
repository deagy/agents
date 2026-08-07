"""Unit tests for roster/orchestration/src/generate_global_plugin.py's
generate_suite_copy(), targeting the git-index-vs-worktree gap a repository
review surfaced: `catalog` is parsed straight off the worktree copy of
catalog.yaml, but the suite-file selection this module builds only
recognizes what `git ls-files` reports (the index). An uncommitted new
role's AGENT.md previously passed generation silently, then still got a
wrapper and an agent-catalog.json entry from generate_agent_wrappers()/
generate_agent_catalog_export() (which read `catalog` directly, not the
tracked set), producing a package with a dangling reference that
`--check` still reported as current.

test_repository_health.py's drift-guard tests always run against the
real, fully-committed repository, so they never exercise this path --
hence a dedicated fixture-based test here.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import generate_global_plugin as ggp  # noqa: E402


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class GenerateSuiteCopyTests(unittest.TestCase):
    def _committed_base_repo(self, root: Path) -> None:
        _init_git_repo(root)
        _write(root / "roster" / "sample-role" / "AGENT.md", "# Sample\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)

    def _plugin_root_with_readme(self, root: Path) -> Path:
        plugin_root = root / "plugins" / "cadre"
        _write(plugin_root / "README.md", "template readme\n")
        return plugin_root

    def test_untracked_role_definition_raises_instead_of_a_dangling_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._committed_base_repo(root)
            # New role's AGENT.md exists on disk (worktree) but was never
            # `git add`ed -- exactly the scenario the review probed.
            _write(root / "roster" / "new-role" / "AGENT.md", "# New\n")
            catalog = {"new-role": {"definition": "new-role/AGENT.md"}}
            plugin_root = self._plugin_root_with_readme(root)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root):
                with self.assertRaisesRegex(ValueError, r"new-role/AGENT\.md"):
                    ggp.generate_suite_copy(catalog, plugin_root)

    def test_tracked_role_definition_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._committed_base_repo(root)
            catalog = {"sample-role": {"definition": "sample-role/AGENT.md"}}
            plugin_root = self._plugin_root_with_readme(root)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root):
                ggp.generate_suite_copy(catalog, plugin_root)

            copied = plugin_root / "suite" / "roster" / "sample-role" / "AGENT.md"
            self.assertTrue(copied.is_file())

    def test_staged_but_uncommitted_role_definition_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._committed_base_repo(root)
            _write(root / "roster" / "staged-role" / "AGENT.md", "# Staged\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            catalog = {"staged-role": {"definition": "staged-role/AGENT.md"}}
            plugin_root = self._plugin_root_with_readme(root)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root):
                ggp.generate_suite_copy(catalog, plugin_root)

            copied = plugin_root / "suite" / "roster" / "staged-role" / "AGENT.md"
            self.assertTrue(copied.is_file())

    def test_migrated_role_with_embedded_triple_dash_in_frontmatter_value_marker_lands_after_real_delimiter(
        self,
    ) -> None:
        """A raw `content.find("---", 3)` would false-match the literal
        `---` embedded in `knowledge_focus` below (which appears before the
        real closing delimiter line), splicing the GENERATED_MARKER into the
        middle of the frontmatter block instead of after it. Proves the
        marker lands after the real closing `---` line and the frontmatter
        block itself is left untouched.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _init_git_repo(root)
            frontmatter_role_text = (
                "---\n"
                "id: sample-role\n"
                "phase: build\n"
                "capability: code_author\n"
                "model: sonnet\n"
                "codex_model: gpt-5.6-terra\n"
                "reasoning_effort: medium\n"
                "knowledge_focus: value with --- embedded before the real delimiter\n"
                "---\n"
                "\n"
                "# Sample Role\n"
                "\n"
                "Body text.\n"
            )
            _write(root / "roster" / "sample-role" / "AGENT.md", frontmatter_role_text)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            catalog = {"sample-role": {"definition": "sample-role/AGENT.md"}}
            plugin_root = self._plugin_root_with_readme(root)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root):
                ggp.generate_suite_copy(catalog, plugin_root)

            copied = plugin_root / "suite" / "roster" / "sample-role" / "AGENT.md"
            content = copied.read_text(encoding="utf-8")

            # The frontmatter block itself (opening delimiter through the
            # real closing delimiter line) must be byte-identical to the
            # source -- the marker must not have spliced into it.
            frontmatter_block = frontmatter_role_text[: frontmatter_role_text.index("---\n\n") + 3]
            self.assertTrue(content.startswith(frontmatter_block))
            self.assertNotIn(ggp.GENERATED_MARKER, frontmatter_block)

            # The marker appears exactly once, after the real closing
            # delimiter and before the prose body.
            self.assertEqual(1, content.count(ggp.GENERATED_MARKER))
            marker_index = content.index(ggp.GENERATED_MARKER)
            body_index = content.index("# Sample Role")
            self.assertLess(len(frontmatter_block), marker_index)
            self.assertLess(marker_index, body_index)


class ReasoningEffortPropagationTests(unittest.TestCase):
    """`parse_catalog_entries` (routing.py) has a hardcoded allowlist of
    catalog.yaml field names it captures; a field missing from that list is
    silently dropped rather than erroring, so adding `reasoning_effort` to
    catalog.yaml without also adding it to that allowlist produced fully
    passing tests and a "current" `--check` while every generated wrapper
    silently omitted `effort:`/`model_reasoning_effort`. Exercises the real
    parser plus both wrapper generators end to end against a real,
    existing role definition (architecture/cloud-architect/AGENT.md) rather
    than mocking either layer, since mocking the parser is exactly what
    would have hidden this bug.
    """

    def test_reasoning_effort_propagates_to_both_wrapper_formats(self) -> None:
        catalog_text = (
            "version: 1\n"
            "agents:\n"
            "  cloud-architect:\n"
            "    definition: architecture/cloud-architect/AGENT.md\n"
            "    phase: design\n"
            "    capability: document_author\n"
            "    model: opus\n"
            "    codex_model: gpt-5.6-sol\n"
            "    reasoning_effort: high\n"
        )
        sys.path.insert(0, str(ROOT / "src"))
        try:
            from routing import parse_catalog_entries
        finally:
            sys.path.pop(0)
        catalog = parse_catalog_entries(catalog_text)
        self.assertEqual("high", catalog["cloud-architect"]["reasoning_effort"])

        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            ggp.generate_agent_wrappers(catalog, plugin_root)
            md_text = (plugin_root / "agents" / "cloud-architect.md").read_text(encoding="utf-8")
        # Codex wrappers are register-side content now (provider/codex-agents/,
        # written by generate-role-metadata), so they come back as content
        # rather than being written into the package tree.
        toml_text = ggp.codex_wrapper_contents(catalog)["agents-cloud-architect.toml"]
        self.assertIn("effort: high", md_text)
        self.assertIn('model_reasoning_effort = "high"', toml_text)

    def test_missing_reasoning_effort_omits_both_fields(self) -> None:
        catalog = {
            "cloud-architect": {
                "definition": "architecture/cloud-architect/AGENT.md",
                "phase": "design",
                "capability": "document_author",
                "model": "opus",
                "codex_model": "gpt-5.6-sol",
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory) / "plugin"
            ggp.generate_agent_wrappers(catalog, plugin_root)
            md_text = (plugin_root / "agents" / "cloud-architect.md").read_text(encoding="utf-8")
        toml_text = ggp.codex_wrapper_contents(catalog)["agents-cloud-architect.toml"]
        self.assertNotIn("effort:", md_text)
        self.assertNotIn("model_reasoning_effort", toml_text)


class ProviderCopyTests(unittest.TestCase):
    """generate_provider_copy(): the register/plugin split's load-bearing step.

    It is the only thing that puts provider contracts into the package, and it
    is also where the two repositories' differing `definition` spellings are
    reconciled -- an area with no coverage when the split first landed.
    """

    def _provider_root(self, root: Path, definition: str = "review/code-reviewer/AGENT.md") -> Path:
        provider = root / "provider"
        (provider / "profiles" / "secure-cloud").mkdir(parents=True)
        (provider / "extensions").mkdir(parents=True)
        (provider / "codex-agents").mkdir(parents=True)
        (provider / "roles" / Path(definition).parent).mkdir(parents=True)
        (provider / "provider.json").write_text('{"id": "cadre"}\n', encoding="utf-8")
        (provider / "profiles" / "secure-cloud" / "profile.json").write_text("{}\n", encoding="utf-8")
        (provider / "roles" / definition).write_text("# Code Reviewer\n", encoding="utf-8")
        (provider / "agent-catalog.json").write_text(
            json.dumps(
                {"schema_version": 1, "agents": {"code-reviewer": {"definition": f"roles/{definition}"}}},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return provider

    def _patched_fresh(self, provider: Path):
        """Make the staleness guard pass for a synthetic fixture, so these
        tests exercise the copy/rewrite logic in isolation from it.
        `test_stale_provider_content_refuses_to_package` covers the guard.
        """
        catalog_text = (provider / "agent-catalog.json").read_text(encoding="utf-8")
        return (
            mock.patch.object(ggp, "PROVIDER_ROOT", provider),
            mock.patch.object(ggp, "agent_catalog_export_content", lambda catalog: catalog_text),
            mock.patch.object(ggp, "codex_wrapper_contents", lambda catalog: {}),
        )

    def test_definition_is_rewritten_to_the_packages_own_suite_copy(self) -> None:
        """The register spells definitions `roles/...` (resolvable beside its
        own agent-catalog.json); the package must spell the same roles
        `suite/roster/...`. The kernel rejects a path escaping the directory
        holding the catalog, so one spelling genuinely cannot serve both.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = self._provider_root(root)
            plugin_root = root / "package"
            plugin_root.mkdir()
            a, b, c = self._patched_fresh(provider)
            with a, b, c:
                ggp.generate_provider_copy({}, plugin_root)

            packaged = json.loads((plugin_root / "agent-catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(
                "suite/roster/review/code-reviewer/AGENT.md",
                packaged["agents"]["code-reviewer"]["definition"],
            )
            # roles/ is register-only: packaging it would be dead weight the
            # package never reads, since it reaches the same files via suite/.
            self.assertFalse((plugin_root / "roles").exists())
            self.assertTrue((plugin_root / "provider.json").is_file())

    def test_unexpected_definition_prefix_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = self._provider_root(root)
            catalog_path = provider / "agent-catalog.json"
            catalog_path.write_text(
                catalog_path.read_text(encoding="utf-8").replace("roles/review", "elsewhere/review"),
                encoding="utf-8",
            )
            plugin_root = root / "package"
            plugin_root.mkdir()
            a, b, c = self._patched_fresh(provider)
            with a, b, c:
                with self.assertRaisesRegex(SystemExit, "generate-role-metadata"):
                    ggp.generate_provider_copy({}, plugin_root)

    def test_committed_register_definitions_resolve_in_both_trees(self) -> None:
        """End-to-end against the real committed provider/: every definition
        must resolve beside the register's own catalog, and its rewritten
        package spelling must resolve inside a generated package. This is the
        regression that shipped in the split -- `cadre sdlc init` silently
        produced generic one-line roles because the package-relative spelling
        did not resolve register-side.
        """
        register = json.loads(
            (ggp.PROVIDER_ROOT / "agent-catalog.json").read_text(encoding="utf-8")
        )["agents"]
        self.assertTrue(register)
        for agent_id, metadata in register.items():
            with self.subTest(agent=agent_id):
                definition = metadata["definition"]
                self.assertTrue(definition.startswith(ggp.PROVIDER_DEFINITION_PREFIX), definition)
                self.assertTrue((ggp.PROVIDER_ROOT / definition).is_file(), definition)

    def test_stale_provider_content_refuses_to_package(self) -> None:
        """Editing a role and running only `generate-plugin` would otherwise
        refresh the package's Claude Code wrappers (built live from the
        catalog) while packaging stale Codex wrappers and a stale catalog
        export -- and a following --check would call the result current.
        """
        catalog = {
            "cloud-architect": {
                "definition": "architecture/cloud-architect/AGENT.md",
                "phase": "design",
                "capability": "document_author",
                "model": "opus",
                "codex_model": "gpt-5.6-sol",
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = self._provider_root(root)
            plugin_root = root / "package"
            plugin_root.mkdir()
            with mock.patch.object(ggp, "PROVIDER_ROOT", provider):
                with self.assertRaisesRegex(SystemExit, "provider/ is stale"):
                    ggp.generate_provider_copy(catalog, plugin_root)


class SharedPolicyOptionalityTests(unittest.TestCase):
    """roster/shared/team-profile.yaml (and any SHARED_POLICIES file) is
    documented as safe to be either missing or emptied. Exercises
    role_wrapper_inputs() directly against a fabricated tree so the
    "no PII in team-profile.yaml" fix's absence-handling claim is actually
    verified by an executed test, not just by code inspection."""

    def _fake_role_tree(self, root: Path) -> None:
        _write(
            root / "roster" / "sample-role" / "AGENT.md",
            "# Sample Role\n\nBody text.\n",
        )

    def _metadata(self) -> dict:
        return {
            "definition": "sample-role/AGENT.md",
            "phase": "build",
            "capability": "code_author",
            "model": "sonnet",
            "codex_model": "gpt-5.6-terra",
        }

    def test_missing_shared_policy_file_is_skipped_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fake_role_tree(root)
            # Deliberately do not create roster/shared/team-profile.yaml.
            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "AGENTS_ROOT", root / "roster"
            ), mock.patch.object(ggp, "SHARED_POLICIES", ["roster/shared/team-profile.yaml"]):
                inputs = ggp.role_wrapper_inputs("sample-role", self._metadata())

        self.assertNotIn("Shared policy: roster/shared/team-profile.yaml", inputs["instructions"])
        # No dangling blank section between the role body and the fixed notes.
        self.assertNotIn("\n\n\n\n", inputs["instructions"])

    def test_emptied_shared_policy_file_is_skipped_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fake_role_tree(root)
            _write(root / "roster" / "shared" / "team-profile.yaml", "   \n")
            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "AGENTS_ROOT", root / "roster"
            ), mock.patch.object(ggp, "SHARED_POLICIES", ["roster/shared/team-profile.yaml"]):
                inputs = ggp.role_wrapper_inputs("sample-role", self._metadata())

        self.assertNotIn("Shared policy: roster/shared/team-profile.yaml", inputs["instructions"])
        self.assertNotIn("\n\n\n\n", inputs["instructions"])

    def test_present_shared_policy_file_is_still_embedded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fake_role_tree(root)
            _write(root / "roster" / "shared" / "team-profile.yaml", "status: active\n")
            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "AGENTS_ROOT", root / "roster"
            ), mock.patch.object(ggp, "SHARED_POLICIES", ["roster/shared/team-profile.yaml"]):
                inputs = ggp.role_wrapper_inputs("sample-role", self._metadata())

        self.assertIn("Shared policy: roster/shared/team-profile.yaml", inputs["instructions"])
        self.assertIn("status: active", inputs["instructions"])


class TierScopedPolicyOptionalityTests(unittest.TestCase):
    """TIER_SCOPED_POLICIES files (e.g. roster/shared/workspace-isolation.md)
    follow the exact same missing/emptied/present optionality contract as
    SHARED_POLICIES, but only for tiers listed against them -- a read-only
    role's wrapper must never see the section at all."""

    def _fake_role_tree(self, root: Path) -> None:
        _write(
            root / "roster" / "sample-role" / "AGENT.md",
            "# Sample Role\n\nBody text.\n",
        )

    def _metadata(self, capability: str) -> dict:
        return {
            "definition": "sample-role/AGENT.md",
            "phase": "build",
            "capability": capability,
            "model": "sonnet",
            "codex_model": "gpt-5.6-terra",
        }

    def test_missing_tier_scoped_policy_file_is_skipped_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fake_role_tree(root)
            # Deliberately do not create roster/shared/workspace-isolation.md.
            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "AGENTS_ROOT", root / "roster"
            ), mock.patch.object(ggp, "SHARED_POLICIES", []), mock.patch.object(
                ggp,
                "TIER_SCOPED_POLICIES",
                {"roster/shared/workspace-isolation.md": frozenset({"code_author"})},
            ):
                inputs = ggp.role_wrapper_inputs("sample-role", self._metadata("code_author"))

        self.assertNotIn("Shared policy: roster/shared/workspace-isolation.md", inputs["instructions"])
        self.assertNotIn("\n\n\n\n", inputs["instructions"])

    def test_emptied_tier_scoped_policy_file_is_skipped_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fake_role_tree(root)
            _write(root / "roster" / "shared" / "workspace-isolation.md", "   \n")
            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "AGENTS_ROOT", root / "roster"
            ), mock.patch.object(ggp, "SHARED_POLICIES", []), mock.patch.object(
                ggp,
                "TIER_SCOPED_POLICIES",
                {"roster/shared/workspace-isolation.md": frozenset({"code_author"})},
            ):
                inputs = ggp.role_wrapper_inputs("sample-role", self._metadata("code_author"))

        self.assertNotIn("Shared policy: roster/shared/workspace-isolation.md", inputs["instructions"])
        self.assertNotIn("\n\n\n\n", inputs["instructions"])

    def test_present_tier_scoped_policy_file_is_embedded_for_listed_tier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fake_role_tree(root)
            _write(root / "roster" / "shared" / "workspace-isolation.md", "Isolate before editing.\n")
            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "AGENTS_ROOT", root / "roster"
            ), mock.patch.object(ggp, "SHARED_POLICIES", []), mock.patch.object(
                ggp,
                "TIER_SCOPED_POLICIES",
                {"roster/shared/workspace-isolation.md": frozenset({"code_author"})},
            ):
                inputs = ggp.role_wrapper_inputs("sample-role", self._metadata("code_author"))

        self.assertIn("Shared policy: roster/shared/workspace-isolation.md", inputs["instructions"])
        self.assertIn("Isolate before editing.", inputs["instructions"])

    def test_tier_scoped_policy_file_absent_for_untiered_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fake_role_tree(root)
            _write(root / "roster" / "shared" / "workspace-isolation.md", "Isolate before editing.\n")
            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "AGENTS_ROOT", root / "roster"
            ), mock.patch.object(ggp, "SHARED_POLICIES", []), mock.patch.object(
                ggp,
                "TIER_SCOPED_POLICIES",
                {"roster/shared/workspace-isolation.md": frozenset({"code_author"})},
            ):
                inputs = ggp.role_wrapper_inputs("sample-role", self._metadata("read_only"))

        self.assertNotIn("Shared policy: roster/shared/workspace-isolation.md", inputs["instructions"])


class GenerateSkillCopiesPackageTargetTests(unittest.TestCase):
    """SKILL_PACKAGE_TARGETS lets specific skills (lifecycle-onboarding,
    lifecycle-review) generate into a sub-plugin directory instead of the
    package root skills/, so cadre-lifecycle can package them as part of an
    optional lifecycle plugin. Everything else must be unaffected: wrong
    depth math here would ship a broken relative-path hint in every ordinary
    skill's "Packaged suite note", not just the two retargeted ones.
    """

    def _skill_repo(self, root: Path, skill_name: str, body: str = "content\n") -> None:
        _init_git_repo(root)
        _write(root / ".agents" / "skills" / skill_name / "SKILL.md", f"---\nname: {skill_name}\n---\n{body}")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)

    def test_unmapped_skill_generates_to_package_root_skills_with_two_level_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._skill_repo(root, "ordinary-skill")
            plugin_root = root / "plugins" / "cadre"

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "SKILLS_ROOT", root / ".agents" / "skills"
            ):
                ggp.generate_skill_copies(plugin_root)

            target = plugin_root / "skills" / "ordinary-skill" / "SKILL.md"
            self.assertTrue(target.is_file())
            self.assertIn("../../suite/roster/", target.read_text(encoding="utf-8"))

    def test_mapped_skill_generates_into_its_package_target_with_matching_depth_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._skill_repo(root, "lifecycle-review")
            plugin_root = root / "plugins" / "cadre"

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "SKILLS_ROOT", root / ".agents" / "skills"
            ):
                ggp.generate_skill_copies(plugin_root)

            old_location = plugin_root / "skills" / "lifecycle-review" / "SKILL.md"
            new_location = plugin_root / "plugins" / "lifecycle" / "skills" / "lifecycle-review" / "SKILL.md"
            self.assertFalse(old_location.exists())
            self.assertTrue(new_location.is_file())
            self.assertIn("../../../../suite/roster/", new_location.read_text(encoding="utf-8"))

    def test_reset_generated_content_clears_nested_target_without_touching_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_root = root / "plugins" / "cadre"
            stale = plugin_root / "plugins" / "lifecycle" / "skills" / "lifecycle-review" / "SKILL.md"
            _write(stale, "stale\n")
            manifest = plugin_root / "plugins" / "lifecycle" / ".claude-plugin" / "plugin.json"
            _write(manifest, "{}\n")

            ggp.reset_generated_content(plugin_root)

            self.assertFalse(stale.exists())
            self.assertTrue(manifest.is_file(), "hand-authored sub-plugin manifest must survive a reset")


class DownstreamReadmeGuardTests(unittest.TestCase):
    """deagy/cadre#97: `generate-plugin --output` against a target that
    already carries its own `.codex-plugin/plugin.json` (i.e. it is itself
    an initialized, hand-authored downstream package, not a fresh
    distribution target) must never clobber that target's own README.md.
    The register's prior guard only checked the marker's *presence*, which
    passes trivially for exactly this repository shape and did nothing to
    stop the clobber -- these tests exercise the actual write_readme/
    remove_readme/compare_readme plumbing that fixes it.
    """

    def _committed_base_repo(self, root: Path) -> None:
        _init_git_repo(root)
        _write(root / "roster" / "sample-role" / "AGENT.md", "# Sample\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)

    def test_generate_suite_copy_write_readme_false_skips_root_readme_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._committed_base_repo(root)
            catalog = {"sample-role": {"definition": "sample-role/AGENT.md"}}
            plugin_root = root / "plugins" / "cadre"
            hand_authored = "# This Downstream Repository's Own README\n"
            _write(plugin_root / "README.md", hand_authored)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root):
                written = ggp.generate_suite_copy(catalog, plugin_root, write_readme=False)

            self.assertEqual(hand_authored, (plugin_root / "README.md").read_text(encoding="utf-8"))
            self.assertNotIn(plugin_root / "README.md", written)
            # suite/README.md is always register-owned, marker or not.
            self.assertTrue((plugin_root / "suite" / "README.md").is_file())
            self.assertIn(plugin_root / "suite" / "README.md", written)

    def test_generate_suite_copy_write_readme_true_still_writes_root_readme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._committed_base_repo(root)
            catalog = {"sample-role": {"definition": "sample-role/AGENT.md"}}
            plugin_root = root / "plugins" / "cadre"
            _write(plugin_root / "README.md", "stale template readme\n")

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root):
                written = ggp.generate_suite_copy(catalog, plugin_root)

            self.assertEqual(
                ggp.PACKAGING_README.read_text(encoding="utf-8"),
                (plugin_root / "README.md").read_text(encoding="utf-8"),
            )
            self.assertIn(plugin_root / "README.md", written)

    def test_reset_generated_content_remove_readme_false_preserves_readme_but_clears_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_root = root / "plugins" / "cadre"
            hand_authored = "# Downstream README\n"
            _write(plugin_root / "README.md", hand_authored)
            _write(plugin_root / "skills" / "some-skill" / "SKILL.md", "stale\n")

            ggp.reset_generated_content(plugin_root, remove_readme=False)

            self.assertEqual(hand_authored, (plugin_root / "README.md").read_text(encoding="utf-8"))
            self.assertFalse((plugin_root / "skills").exists())

    def test_reset_generated_content_default_still_removes_readme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_root = root / "plugins" / "cadre"
            _write(plugin_root / "README.md", "stale template readme\n")

            ggp.reset_generated_content(plugin_root)

            self.assertFalse((plugin_root / "README.md").exists())

    def test_files_equal_compare_readme_false_ignores_root_readme_difference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            _write(left / "README.md", "generated readme\n")
            _write(right / "README.md", "downstream's own readme\n")
            _write(left / "skills" / "a" / "SKILL.md", "same\n")
            _write(right / "skills" / "a" / "SKILL.md", "same\n")

            self.assertFalse(ggp.files_equal(left, right))
            self.assertTrue(ggp.files_equal(left, right, compare_readme=False))

    def test_files_equal_compare_readme_false_still_catches_other_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            _write(left / "README.md", "downstream's own readme\n")
            _write(right / "README.md", "downstream's own readme\n")
            _write(left / "skills" / "a" / "SKILL.md", "new content\n")
            _write(right / "skills" / "a" / "SKILL.md", "stale content\n")

            self.assertFalse(ggp.files_equal(left, right, compare_readme=False))

    def test_generate_package_write_readme_false_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._committed_base_repo(root)
            catalog = {"sample-role": {"definition": "sample-role/AGENT.md"}}
            plugin_root = root / "plugins" / "cadre"
            hand_authored = "# This Downstream Repository's Own README\n"
            _write(plugin_root / "README.md", hand_authored)
            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(
                ggp, "generate_agent_wrappers", lambda catalog, plugin_root: []
            ), mock.patch.object(
                ggp, "generate_provider_copy", lambda catalog, plugin_root: []
            ), mock.patch.object(
                ggp, "generate_bin_wrapper", lambda plugin_root: plugin_root / "bin" / "cadre"
            ), mock.patch.object(
                ggp, "generate_skill_copies", lambda plugin_root: []
            ):
                ggp.generate_package(catalog, plugin_root, write_readme=False)

            self.assertEqual(hand_authored, (plugin_root / "README.md").read_text(encoding="utf-8"))


class MainCliDownstreamReadmeGuardTests(unittest.TestCase):
    """End-to-end regression for deagy/cadre#97 through the real CLI
    entrypoint, against this repository's own real catalog/provider/roster
    content (same pattern test_repository_health.py's generated_package()
    uses) -- proves the fix works through main()'s actual argument parsing,
    not just the underlying functions in isolation.
    """

    SCRIPT = Path(__file__).resolve().parents[1] / "src" / "generate_global_plugin.py"
    REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), *args],
            cwd=self.REPOSITORY_ROOT, check=False, capture_output=True, text=True, encoding="utf-8",
        )

    def test_existing_marker_preserves_downstream_readme_and_can_be_forced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "downstream-package"
            hand_authored = "# This Downstream Repository's Own README\n"
            _write(target / "README.md", hand_authored)
            _write(target / ".codex-plugin" / "plugin.json", "{}\n")

            result = self._run("--output", str(target))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("README.md left untouched", result.stderr)
            self.assertEqual(hand_authored, (target / "README.md").read_text(encoding="utf-8"))
            # Everything else still regenerated normally.
            self.assertTrue((target / "skills").is_dir())
            self.assertTrue((target / "agents").is_dir())

            forced = self._run("--output", str(target), "--force-readme")
            self.assertEqual(0, forced.returncode, forced.stderr)
            self.assertNotIn("README.md left untouched", forced.stderr)
            self.assertEqual(
                ggp.PACKAGING_README.read_text(encoding="utf-8"),
                (target / "README.md").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
