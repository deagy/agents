from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from resolve import (  # noqa: E402
    OverlayError,
    _load_structured,
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

    # -- Threat-model bypass regression tests --------------------------------
    # These reproduce the five demonstrated bypasses of the old two-sentinel
    # ("allowed" / "never") equality check, which the ranked-vocabulary check
    # must now reject.

    def test_autonomy_overlay_rejects_capitalized_allowed(self) -> None:
        # Bypass 1: case variation ("Allowed" != "allowed") slipped past the
        # old exact string-equality comparison.
        self._write_overlay("agent-autonomy.yaml", "repository:\n  merge: Allowed\n")
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_autonomy_overlay_rejects_trailing_whitespace_allowed(self) -> None:
        # Bypass 2: whitespace variation ("allowed " != "allowed") slipped
        # past the old exact string-equality comparison.
        self._write_overlay("agent-autonomy.yaml", "repository:\n  merge: \"allowed \"\n")
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_autonomy_overlay_rejects_non_string_list_value(self) -> None:
        # Bypass 3a: a non-string value (a list) never equals the "allowed"
        # or "never" sentinel strings, so neither old branch triggered.
        self._write_overlay("agent-autonomy.yaml", "repository:\n  merge:\n    - allowed\n")
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_autonomy_overlay_rejects_null_value(self) -> None:
        # Bypass 3b: null never equals the "allowed" or "never" sentinel
        # strings either.
        self._write_overlay("agent-autonomy.yaml", "repository:\n  merge: null\n")
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_autonomy_overlay_rejects_loosening_between_non_sentinel_values(self) -> None:
        # Bypass 4: mutations.production defaults to human_approval; an
        # overlay loosening it to explicit_task_authorization (a genuinely
        # weaker value used elsewhere in the same file) involves neither the
        # literal string "allowed" nor "never", so it slipped past the old
        # check entirely.
        self._write_overlay(
            "agent-autonomy.yaml", "mutations:\n  production: explicit_task_authorization\n"
        )
        with self.assertRaises(OverlayError):
            resolve_shared_config("agent-autonomy.yaml", start=self.project)

    def test_autonomy_overlay_accepts_genuine_narrowing_between_ranked_values(self) -> None:
        # A genuinely valid narrowing between two non-sentinel ranked values:
        # repository.commit defaults to on_request (rank 3); tightening it to
        # human_approval (rank 8) is a real narrowing and must still work.
        self._write_overlay("agent-autonomy.yaml", "repository:\n  commit: human_approval\n")
        resolved = resolve_shared_config("agent-autonomy.yaml", start=self.project)
        self.assertEqual(resolved["repository"]["commit"], "human_approval")

    def test_autonomy_overlay_accepts_identical_value_as_noop(self) -> None:
        # An overlay setting a leaf to the exact same value as the base
        # default is always a no-op and must remain accepted.
        self._write_overlay("agent-autonomy.yaml", "mutations:\n  production: human_approval\n")
        resolved = resolve_shared_config("agent-autonomy.yaml", start=self.project)
        self.assertEqual(resolved["mutations"]["production"], "human_approval")

    def test_malformed_overlay_fails_closed(self) -> None:
        self._write_overlay("library-standards.yaml", "not: [valid, yaml, :::\n")
        with self.assertRaises(Exception):
            resolve_shared_config("library-standards.yaml", start=self.project)

    def test_emptied_overlay_resolves_as_no_op_rather_than_failing_closed(self) -> None:
        # A project may intentionally clear an overlay back to "no override"
        # by emptying the file rather than deleting it. That must behave
        # like no overlay at all, not raise OverlayError("root must be a
        # mapping") -- yaml.safe_load("") returns None, not {}.
        self._write_overlay("library-standards.yaml", "   \n")
        resolved = resolve_shared_config("library-standards.yaml", start=self.project)
        self.assertTrue(resolved["selection_rules"]["require_pinned_versions_in_go_mod_or_tool_definition"])


class LoadStructuredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="load-structured-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_empty_yaml_file_loads_as_empty_mapping(self) -> None:
        path = self.root / "empty.yaml"
        path.write_text("   \n", encoding="utf-8")
        self.assertEqual({}, _load_structured(path))

    def test_truly_empty_yaml_file_loads_as_empty_mapping(self) -> None:
        path = self.root / "empty.yaml"
        path.write_text("", encoding="utf-8")
        self.assertEqual({}, _load_structured(path))

    def test_non_mapping_yaml_content_still_fails_closed(self) -> None:
        path = self.root / "list.yaml"
        path.write_text("- one\n- two\n", encoding="utf-8")
        with self.assertRaises(OverlayError):
            _load_structured(path)


if __name__ == "__main__":
    unittest.main()
