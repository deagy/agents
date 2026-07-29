"""Unit tests for agents/orchestration/src/generate_global_plugin.py's
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
        _write(root / "agents" / "sample-role" / "AGENT.md", "# Sample\n")
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
            _write(root / "agents" / "new-role" / "AGENT.md", "# New\n")
            catalog = {"new-role": {"definition": "new-role/AGENT.md"}}
            plugin_root = self._plugin_root_with_readme(root)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(ggp, "PLUGIN_ROOT", plugin_root):
                with self.assertRaisesRegex(ValueError, r"new-role/AGENT\.md"):
                    ggp.generate_suite_copy(catalog, plugin_root)

    def test_tracked_role_definition_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._committed_base_repo(root)
            catalog = {"sample-role": {"definition": "sample-role/AGENT.md"}}
            plugin_root = self._plugin_root_with_readme(root)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(ggp, "PLUGIN_ROOT", plugin_root):
                ggp.generate_suite_copy(catalog, plugin_root)

            copied = plugin_root / "suite" / "agents" / "sample-role" / "AGENT.md"
            self.assertTrue(copied.is_file())

    def test_staged_but_uncommitted_role_definition_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._committed_base_repo(root)
            _write(root / "agents" / "staged-role" / "AGENT.md", "# Staged\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            catalog = {"staged-role": {"definition": "staged-role/AGENT.md"}}
            plugin_root = self._plugin_root_with_readme(root)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(ggp, "PLUGIN_ROOT", plugin_root):
                ggp.generate_suite_copy(catalog, plugin_root)

            copied = plugin_root / "suite" / "agents" / "staged-role" / "AGENT.md"
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
            _write(root / "agents" / "sample-role" / "AGENT.md", frontmatter_role_text)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            catalog = {"sample-role": {"definition": "sample-role/AGENT.md"}}
            plugin_root = self._plugin_root_with_readme(root)

            with mock.patch.object(ggp, "REPOSITORY_ROOT", root), mock.patch.object(ggp, "PLUGIN_ROOT", plugin_root):
                ggp.generate_suite_copy(catalog, plugin_root)

            copied = plugin_root / "suite" / "agents" / "sample-role" / "AGENT.md"
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
    parser plus generate_agent_wrappers() end to end against a real,
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
            toml_text = (plugin_root / "codex-agents" / "agents-cloud-architect.toml").read_text(encoding="utf-8")
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
            toml_text = (plugin_root / "codex-agents" / "agents-cloud-architect.toml").read_text(encoding="utf-8")
        self.assertNotIn("effort:", md_text)
        self.assertNotIn("model_reasoning_effort", toml_text)


if __name__ == "__main__":
    unittest.main()
