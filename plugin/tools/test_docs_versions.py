#!/usr/bin/env python3
"""Guard against hand-maintained version coordinates rotting in the docs.

Install instructions in this repository used to pin a marketplace ref
(`/plugin marketplace add deagy/cadre-lifecycle@v0.9.8`) and a clone ref
(`git clone --branch v0.9.8`). Nothing checked them, so they drifted: three
different documents across two repositories quoted three different tags
(v0.7.0, v0.9.8, v0.10.1), and this repository's own README ended up
disclaiming its own pinned tag and telling readers to go look up the
releases page instead. A user who copied a stale tag got a plugin whose
`provider.json` declared a kernel-compatibility window ten minor versions
behind the kernel they had, and the bootstrap script then fail-closed with
no path forward.

The fix is to stop writing the coordinate down. `/plugin install` resolves
the version from each plugin's own `.claude-plugin/plugin.json`, and
`release.yml` only tags `main` from a state where all plugin manifests
agree -- so the marketplace ref does not need a tag at all. This test keeps
it that way.

It also asserts the second class of the same bug: prose that quotes an
Agentic SDLC kernel version must agree with `provider.json`'s
`kernel_compatibility`. `provider.json` carries two unrelated version lines
-- its own `version` (the provider-manifest version, 0.3.x) and
`kernel_compatibility` (the kernel range, 0.13.0+) -- and every install
message in both repositories used to quote the former while meaning the
latter.

    python3 -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories whose Markdown this repository does not author:
#   suite/      - regenerated verbatim from deagy/cadre by `cadre
#                 generate-plugin`; fix the source there, not here (the
#                 register has its own copy of this test).
#   node_modules/, .git/ - vendored / VCS internals.
EXCLUDED_DIRS = frozenset({"suite", "node_modules", ".git"})

# CHANGELOG.md legitimately records historical tags ("v0.7.0 -- ...").
EXCLUDED_FILES = frozenset({"CHANGELOG.md"})

# Prose that intentionally cites a historical release may opt out by wrapping
# itself in these markers.
HISTORY_OPEN = "<!-- version-history -->"
HISTORY_CLOSE = "<!-- /version-history -->"

PINNED_MARKETPLACE = re.compile(r"marketplace add\s+\S*cadre-lifecycle@v[\d.]+")
PINNED_CLONE = re.compile(r"clone\s+--branch\s+v[\d.]+")
# Two spellings appear in practice: prose ("Agentic SDLC v0.13.0") and a
# backticked package reference followed by a release link
# ("Requires `agentic-sdlc` [v0.13.0](...)+"). Both drifted independently --
# the second form sat two minor versions behind for several releases because
# a regex written only for the first form never saw it.
KERNEL_VERSION_PROSE = re.compile(
    r"(?:Agentic SDLC\s+v|`agentic-sdlc`\s*\[v)(\d+\.\d+)"
)


def _strip_history_blocks(text: str) -> str:
    """Blank out opted-out regions, preserving line numbering for reporting."""
    out, keeping = [], True
    for line in text.splitlines():
        if HISTORY_OPEN in line:
            keeping = False
        if keeping:
            out.append(line)
        else:
            out.append("")
        if HISTORY_CLOSE in line:
            keeping = True
    return "\n".join(out)


def markdown_files() -> list[Path]:
    return [
        path
        for path in sorted(REPO_ROOT.rglob("*.md"))
        if not (EXCLUDED_DIRS & set(path.relative_to(REPO_ROOT).parts))
        and path.name not in EXCLUDED_FILES
    ]


def _offenders(pattern: re.Pattern[str]) -> list[str]:
    hits = []
    for path in markdown_files():
        text = _strip_history_blocks(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                rel = path.relative_to(REPO_ROOT)
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


class TestDocsCarryNoPinnedTags(unittest.TestCase):
    def test_no_pinned_marketplace_ref(self) -> None:
        hits = _offenders(PINNED_MARKETPLACE)
        self.assertEqual(
            hits,
            [],
            "Install docs must not pin the marketplace ref to a tag -- the version "
            "comes from each plugin's own .claude-plugin/plugin.json, and a written-down "
            "tag only goes stale. Use `/plugin marketplace add deagy/cadre-lifecycle`.\n"
            + "\n".join(hits),
        )

    def test_no_pinned_clone_ref(self) -> None:
        hits = _offenders(PINNED_CLONE)
        self.assertEqual(
            hits,
            [],
            "Install docs must not clone at a hardcoded tag; use a plain `git clone` and "
            "let the reader check out a specific revision if their policy needs one.\n"
            + "\n".join(hits),
        )


class TestKernelVersionProseMatchesProvider(unittest.TestCase):
    def test_quoted_kernel_version_matches_provider_manifest(self) -> None:
        manifest = json.loads((REPO_ROOT / "provider.json").read_text(encoding="utf-8"))
        minimum = manifest["kernel_compatibility"]["minimum"]
        supported_series = ".".join(minimum.split(".")[:2])

        mismatches = []
        for path in markdown_files():
            text = _strip_history_blocks(path.read_text(encoding="utf-8"))
            for lineno, line in enumerate(text.splitlines(), start=1):
                for found in KERNEL_VERSION_PROSE.findall(line):
                    if found != supported_series:
                        rel = path.relative_to(REPO_ROOT)
                        mismatches.append(f"{rel}:{lineno}: quotes v{found}, expected v{supported_series}")

        self.assertEqual(
            mismatches,
            [],
            "Prose quoting an Agentic SDLC kernel version must agree with provider.json's "
            f"kernel_compatibility.minimum ({minimum}). Note provider.json's own `version` "
            "field is a different version line -- quoting it here is the exact bug this "
            "guards.\n" + "\n".join(mismatches),
        )


if __name__ == "__main__":
    unittest.main()
