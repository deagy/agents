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


if __name__ == "__main__":
    unittest.main()
