from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from resolve import (  # noqa: E402
    OverlayError,
    deep_merge,
    find_project_overlay,
    resolve_shared_config,
)


class DeepMergeTests(unittest.TestCase):
    def test_overlay_wins_and_recurses_into_nested_dicts(self) -> None:
        base = {"a": 1, "nested": {"x": 1, "y": 2}}
        overlay = {"a": 2, "nested": {"y": 3, "z": 4}}
        self.assertEqual(
            deep_merge(base, overlay),
            {"a": 2, "nested": {"x": 1, "y": 3, "z": 4}},
        )

    def test_overlay_replaces_lists_wholesale(self) -> None:
        base = {"items": [1, 2, 3]}
        overlay = {"items": [9]}
        self.assertEqual(deep_merge(base, overlay), {"items": [9]})


class ProjectBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="shared-overlay-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _make_project(self, overlay_filename: str | None, overlay_content: str = "") -> Path:
        (self.root / ".git").mkdir()
        nested = self.root / "src" / "pkg"
        nested.mkdir(parents=True)
        if overlay_filename:
            overlay_dir = self.root / ".agents" / "shared"
            overlay_dir.mkdir(parents=True)
            (overlay_dir / overlay_filename).write_text(overlay_content, encoding="utf-8")
        return nested

    def test_finds_overlay_by_walking_up_to_git_boundary(self) -> None:
        nested = self._make_project("team-profile.yaml", "status: active\n")
        found = find_project_overlay("team-profile.yaml", start=nested)
        self.assertEqual(found, self.root / ".agents" / "shared" / "team-profile.yaml")

    def test_does_not_find_overlay_above_git_boundary(self) -> None:
        nested = self._make_project(None)
        (self.root.parent / ".agents" / "shared").mkdir(parents=True, exist_ok=True)
        (self.root.parent / ".agents" / "shared" / "team-profile.yaml").write_text("status: draft\n", encoding="utf-8")
        try:
            found = find_project_overlay("team-profile.yaml", start=nested)
            self.assertIsNone(found)
        finally:
            (self.root.parent / ".agents" / "shared" / "team-profile.yaml").unlink()

    def test_returns_none_when_no_overlay_exists(self) -> None:
        nested = self._make_project(None)
        self.assertIsNone(find_project_overlay("team-profile.yaml", start=nested))


class ResolveSharedConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="shared-overlay-")
        self.root = Path(self.temporary.name)
        (self.root / ".git").mkdir()
        self.project = self.root / "src"
        self.project.mkdir()
        self.overlay_dir = self.root / ".agents" / "shared"
        self.overlay_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_overlay(self, filename: str, content: str) -> None:
        (self.overlay_dir / filename).write_text(content, encoding="utf-8")

    def test_structured_overlay_merges_over_default(self) -> None:
        self._write_overlay("library-standards.yaml", "selection_rules:\n  require_license_review: false\n")
        resolved = resolve_shared_config("library-standards.yaml", start=self.project)
        self.assertFalse(resolved["selection_rules"]["require_license_review"])
        # unrelated default keys survive the merge untouched
        self.assertTrue(resolved["selection_rules"]["require_pinned_versions_in_go_mod_or_tool_definition"])

    def test_markdown_overlay_appends_rather_than_replaces(self) -> None:
        self._write_overlay("technology-standards.md", "Use RDS instead of self-hosted Postgres.\n")
        resolved = resolve_shared_config("technology-standards.md", start=self.project)
        self.assertIn("# Technology Standards", resolved)
        self.assertIn("Use RDS instead of self-hosted Postgres.", resolved)
        self.assertIn("Project addendum", resolved)

    def test_no_overlay_returns_default_unchanged(self) -> None:
        resolved = resolve_shared_config("technology-standards.md", start=self.project)
        self.assertIn("# Technology Standards", resolved)
        self.assertNotIn("Project addendum", resolved)

    def test_autonomy_overlay_may_narrow(self) -> None:
        self._write_overlay(
            "agent-autonomy.yaml",
            "repository:\n  commit: human_approval\n",
        )
        resolved = resolve_shared_config("agent-autonomy.yaml", start=self.project)
        self.assertEqual(resolved["repository"]["commit"], "human_approval")
        # untouched keys keep their global default
        self.assertEqual(resolved["repository"]["merge"], "never")

    def test_autonomy_overlay_rejects_loosening_never(self) -> None:
        self._write_overlay("agent-autonomy.yaml", "repository:\n  merge: allowed\n")
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_autonomy_overlay_rejects_loosening_to_allowed(self) -> None:
        self._write_overlay("agent-autonomy.yaml", "mutations:\n  production: allowed\n")
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_autonomy_overlay_rejects_touching_fixed_keys(self) -> None:
        self._write_overlay("agent-autonomy.yaml", "default_rule: allow_unless_denied\n")
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_autonomy_overlay_rejects_undefined_key(self) -> None:
        self._write_overlay("agent-autonomy.yaml", "repository:\n  time_travel: allowed\n")
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_malformed_overlay_fails_closed(self) -> None:
        self._write_overlay("library-standards.yaml", "not: [valid, yaml, :::\n")
        with self.assertRaises(Exception):
            resolve_shared_config("library-standards.yaml", start=self.project)


if __name__ == "__main__":
    unittest.main()
