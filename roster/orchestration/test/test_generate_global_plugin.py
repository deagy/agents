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


if __name__ == "__main__":
    unittest.main()
