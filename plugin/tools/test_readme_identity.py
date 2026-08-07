#!/usr/bin/env python3
"""Guard against README.md being silently clobbered by an unsafe
`cadre generate-plugin --output` run against this checkout's root.

The register's generator (`deagy/cadre`'s `generate_global_plugin.py`) has a
safety guard that refuses to run against a non-empty `--output` directory
unless it already contains a `.codex-plugin/plugin.json` -- but this
repository has one of its own (`cadre-lifecycle` is itself a packaged
plugin), so that guard passes trivially and does not stop a clobber. The
guard's actual fix is tracked upstream (deagy/cadre#97) since this
repository does not own that generator's code; see README.md's
"Regenerating Assets" section and CLAUDE.md's "Regeneration guard caveat"
for the documented-but-not-yet-structurally-enforced procedure this test
backstops (deagy/cadre-lifecycle#3).

This is a positive-assertion test, not a diff against the generator's
template: that template lives in the register, not here, so this test
cannot compare against it directly. Instead it asserts that README.md still
carries this repository's own identity -- the 4-plugin split and the
Installing sub-headings -- content the generic single-plugin template does
not produce. If a clobber ever replaces README.md with that template, this
test fails closed instead of a human having to notice.

    python3 -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every plugin manifest this repository actually ships (see the table in
# AGENTS.md's "Project Structure & Module Organization").
PLUGIN_NAMES = (
    "cadre",
    "cadre-lifecycle-core",
    "cadre-lifecycle-github",
    "cadre-lifecycle-gitlab",
)

# Content only this hand-authored README has. The register's template
# describes a standalone single-plugin repository and would never produce
# a generated-vs-hand-authored table or a pointer to the canonical install
# guide, so their absence is a reliable clobber signal.
IDENTITY_MARKERS = (
    "## What is generated and what is not",
    "docs/INSTALL.md",
    "It is **not a\nrepository**",
)


class ReadmeIdentityTests(unittest.TestCase):
    """README.md must keep describing this repository's actual 4-plugin
    split, not the register's generic single-plugin template."""

    def setUp(self) -> None:
        self.path = REPO_ROOT / "README.md"
        self.assertTrue(self.path.is_file(), f"{self.path} is missing")
        self.text = self.path.read_text(encoding="utf-8")

    def test_title_is_this_directorys_own(self) -> None:
        """The title was `# Cadre Lifecycle` until the monorepo merge, when
        this stopped being a repository and became a directory inside one."""
        self.assertTrue(
            self.text.startswith("# `plugin/` — the packaged distribution\n"),
            "plugin/README.md's title has changed -- possible clobber by the "
            "generator's template, which describes a standalone single-plugin "
            "repository this directory is not",
        )

    def test_names_all_four_plugins(self) -> None:
        for name in PLUGIN_NAMES:
            self.assertIn(
                name,
                self.text,
                f"README.md no longer mentions the {name!r} plugin -- "
                "possible clobber by the register's generic single-plugin "
                "template (see deagy/cadre-lifecycle#3)",
            )

    def test_carries_its_own_identity_markers(self) -> None:
        for marker in IDENTITY_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(
                    marker,
                    self.text,
                    f"plugin/README.md is missing {marker!r} -- possible clobber "
                    "by the generator's template",
                )

    def test_does_not_reintroduce_install_instructions(self) -> None:
        """Install steps belong in docs/INSTALL.md only.

        Three documents quoting three different stale version tags is what
        one canonical page exists to prevent; a second copy here is how that
        starts again.
        """
        for command in ("/plugin marketplace add", "codex plugin marketplace add"):
            with self.subTest(command=command):
                self.assertNotIn(command, self.text)


if __name__ == "__main__":
    unittest.main()
