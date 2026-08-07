#!/usr/bin/env python3
"""Tests for tools/apply_regeneration.py.

apply_regeneration() is the one thing standing between an automated
regenerate.yml run and silently clobbering (or silently skipping) content in
this checkout -- see that script's module docstring for why README.md must
never be touched and why plugins/lifecycle-github/ and
plugins/lifecycle-gitlab/ must never be touched either.

    python3 -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_regeneration  # noqa: E402


class ApplyRegenerationTests(unittest.TestCase):
    def _scratch_tree(self, root: Path) -> Path:
        generated = root / "generated"
        (generated / "skills" / "role-discovery").mkdir(parents=True)
        (generated / "skills" / "role-discovery" / "SKILL.md").write_text("new skill\n", encoding="utf-8")
        (generated / "agents").mkdir()
        (generated / "agents" / "backend-engineer.md").write_text("new agent\n", encoding="utf-8")
        (generated / "suite").mkdir()
        (generated / "suite" / "roster.yaml").write_text("new suite\n", encoding="utf-8")
        (generated / "bin").mkdir()
        (generated / "bin" / "cadre").write_text("#!/bin/sh\nnew wrapper\n", encoding="utf-8")
        (generated / "provider.json").write_text('{"new": true}\n', encoding="utf-8")
        (generated / "agent-catalog.json").write_text('{"new": true}\n', encoding="utf-8")
        (generated / "profiles").mkdir()
        (generated / "extensions").mkdir()
        (generated / "codex-agents").mkdir()
        (generated / "plugins" / "lifecycle" / "skills" / "lifecycle-onboarding").mkdir(parents=True)
        (generated / "plugins" / "lifecycle" / "skills" / "lifecycle-onboarding" / "SKILL.md").write_text(
            "new onboarding\n", encoding="utf-8"
        )
        (generated / "README.md").write_text("new readme -- must never be applied\n", encoding="utf-8")
        return generated

    def _target_tree(self, root: Path) -> Path:
        target = root / "target"
        target.mkdir()
        (target / "README.md").write_text("hand-authored readme, must survive\n", encoding="utf-8")
        (target / "bin").mkdir()
        (target / "bin" / "cadre").write_text("#!/bin/sh\nold wrapper\n", encoding="utf-8")
        (target / "plugins" / "lifecycle-github" / "skills" / "lifecycle-onboarding-github").mkdir(parents=True)
        (target / "plugins" / "lifecycle-github" / "skills" / "lifecycle-onboarding-github" / "SKILL.md").write_text(
            "github-specific fork, must survive untouched\n", encoding="utf-8"
        )
        (target / "plugins" / "lifecycle" / ".claude-plugin").mkdir(parents=True)
        (target / "plugins" / "lifecycle" / ".claude-plugin" / "plugin.json").write_text(
            '{"version": "0.8.0"}\n', encoding="utf-8"
        )
        return target

    def test_generated_content_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = self._scratch_tree(root)
            target = self._target_tree(root)

            apply_regeneration.apply_regeneration(generated, target)

            self.assertEqual("new skill\n", (target / "skills" / "role-discovery" / "SKILL.md").read_text())
            self.assertEqual("new agent\n", (target / "agents" / "backend-engineer.md").read_text())
            self.assertEqual("new suite\n", (target / "suite" / "roster.yaml").read_text())
            self.assertEqual("#!/bin/sh\nnew wrapper\n", (target / "bin" / "cadre").read_text())
            self.assertEqual('{"new": true}\n', (target / "provider.json").read_text())
            self.assertEqual(
                "new onboarding\n",
                (target / "plugins" / "lifecycle" / "skills" / "lifecycle-onboarding" / "SKILL.md").read_text(),
            )

    def test_readme_is_never_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = self._scratch_tree(root)
            target = self._target_tree(root)

            apply_regeneration.apply_regeneration(generated, target)

            self.assertEqual("hand-authored readme, must survive\n", (target / "README.md").read_text())

    def test_forge_specific_plugin_forks_are_never_touched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = self._scratch_tree(root)
            target = self._target_tree(root)

            apply_regeneration.apply_regeneration(generated, target)

            forked = target / "plugins" / "lifecycle-github" / "skills" / "lifecycle-onboarding-github" / "SKILL.md"
            self.assertEqual("github-specific fork, must survive untouched\n", forked.read_text())

    def test_hand_authored_plugin_manifests_are_never_touched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = self._scratch_tree(root)
            target = self._target_tree(root)

            apply_regeneration.apply_regeneration(generated, target)

            manifest = target / "plugins" / "lifecycle" / ".claude-plugin" / "plugin.json"
            self.assertEqual('{"version": "0.8.0"}\n', manifest.read_text())

    def test_missing_generated_member_removes_stale_target_content(self) -> None:
        """A generated dir absent from the scratch output (e.g. an emptied
        skills/) must still be reflected in the target -- this is a real
        regeneration outcome (a skill or role removed upstream), not a bug
        to guard against.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = self._scratch_tree(root)
            target = self._target_tree(root)
            stale = target / "skills" / "retired-skill"
            stale.mkdir(parents=True)
            (stale / "SKILL.md").write_text("stale\n", encoding="utf-8")

            apply_regeneration.apply_regeneration(generated, target)

            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
