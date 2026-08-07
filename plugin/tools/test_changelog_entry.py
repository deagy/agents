#!/usr/bin/env python3
"""Tests for tools/changelog_entry.py.

`.github/workflows/release.yml` trusts this script's output verbatim as a
GitHub Release's body -- a heading regex that's too loose or too strict
either leaks the next version's content into this one's Release, or ships an
empty one. Both are silent until someone reads the published Release page.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import changelog_entry  # noqa: E402

SAMPLE = """\
# Changelog

Intro text that must never be mistaken for a version's own body.

## [0.2.0](https://example.com/releases/tag/v0.2.0) - 2026-01-02

### Added

- Something new.

## [0.1.0](https://example.com/releases/tag/v0.1.0) - 2026-01-01

### Added

- First release.
"""


class ExtractEntryTests(unittest.TestCase):
    def test_extracts_only_the_named_versions_body(self) -> None:
        body = changelog_entry.extract_entry("0.2.0", SAMPLE)
        self.assertIn("Something new.", body)
        self.assertNotIn("First release.", body)
        self.assertNotIn("## [0.2.0]", body)

    def test_last_entry_runs_to_end_of_file(self) -> None:
        body = changelog_entry.extract_entry("0.1.0", SAMPLE)
        self.assertIn("First release.", body)

    def test_missing_version_fails_loudly_instead_of_returning_empty(self) -> None:
        with self.assertRaisesRegex(SystemExit, "no CHANGELOG.md entry found"):
            changelog_entry.extract_entry("9.9.9", SAMPLE)

    def test_a_heading_without_a_release_link_is_not_matched(self) -> None:
        unlinked = "## [0.3.0] - 2026-01-03\n\nbody\n"
        with self.assertRaisesRegex(SystemExit, "no CHANGELOG.md entry found"):
            changelog_entry.extract_entry("0.3.0", unlinked)

    def test_this_repositorys_own_changelog_has_an_entry_for_its_current_version(self) -> None:
        import plugin_version

        version = plugin_version.read_versions()["claude"]
        text = changelog_entry.CHANGELOG_PATH.read_text(encoding="utf-8")
        body = changelog_entry.extract_entry(version, text)
        self.assertTrue(body.strip())


if __name__ == "__main__":
    unittest.main()
