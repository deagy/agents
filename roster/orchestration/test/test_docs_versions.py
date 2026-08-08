#!/usr/bin/env python3
"""Guard against hand-maintained version coordinates rotting in the docs.

This repository's install instructions used to pin a marketplace ref
archived-ref-ok: next line quotes the pre-merge string as the bug's example.
(`/plugin marketplace add deagy/cadre-lifecycle@v0.7.0`) and a clone ref
(`git clone --branch v0.7.0`). Nothing checked them, so they drifted: this
repository's README and RUNBOOK quoted v0.7.0, `packaging/plugin-README.md`
quoted v0.9.8, and the actual release was v0.10.1. A user who copied a stale
tag got a plugin whose `provider.json` declared a kernel-compatibility window
ten minor versions behind the kernel they had.

`packaging/plugin-README.md` matters most here: it is the *template* the
generator renders into the downstream distribution's README, so a stale tag
written there propagates on every regeneration.

The fix is to stop writing the coordinate down -- `/plugin install` resolves
the version from the plugin's own manifest, so the marketplace ref does not
need a tag at all. This test keeps it that way.

It also asserts the second class of the same bug: prose quoting an Agentic
SDLC kernel version must agree with `provider/provider.json`'s
`kernel_compatibility`. That manifest carries two unrelated version lines --
its own `version` (the provider-manifest version, 0.3.x) and
`kernel_compatibility` (the kernel range, 0.13.0+) -- and every install
message here used to quote the former while meaning the latter. See
`bin/cadre.py`'s `sdlc_install_message()` and
`generate_global_plugin.py`'s `kernel_requirement_text()` for the runtime
side of the same rule.

    python3 -m unittest discover -s roster/orchestration/test -p "test_*.py"
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

# Directories whose Markdown this repository does not hand-author, or that
# are not documentation at all.
EXCLUDED_DIRS = frozenset({".git", "node_modules", "dist", "build", ".venv"})

# CHANGELOG.md legitimately records historical tags.
EXCLUDED_FILES = frozenset({"CHANGELOG.md"})

HISTORY_OPEN = "<!-- version-history -->"
HISTORY_CLOSE = "<!-- /version-history -->"

PINNED_MARKETPLACE = re.compile(r"marketplace add\s+\S*cadre-lifecycle@v[\d.]+")
PINNED_CLONE = re.compile(r"clone\s+--branch\s+v[\d.]+")
# Both spellings seen in practice -- plain prose, and a backticked package
# reference followed by a release link.
KERNEL_VERSION_PROSE = re.compile(r"(?:Agentic SDLC\s+v|`agentic-sdlc`\s*\[v)(\d+\.\d+)")


def _strip_history_blocks(text: str) -> str:
    """Blank out opted-out regions, preserving line numbering for reporting."""
    out, keeping = [], True
    for line in text.splitlines():
        if HISTORY_OPEN in line:
            keeping = False
        out.append(line if keeping else "")
        if HISTORY_CLOSE in line:
            keeping = True
    return "\n".join(out)


def markdown_files() -> list[Path]:
    return [
        path
        for path in sorted(REPOSITORY_ROOT.rglob("*.md"))
        if not (EXCLUDED_DIRS & set(path.relative_to(REPOSITORY_ROOT).parts))
        and path.name not in EXCLUDED_FILES
    ]


def _offenders(pattern: re.Pattern[str]) -> list[str]:
    hits = []
    for path in markdown_files():
        text = _strip_history_blocks(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(REPOSITORY_ROOT)}:{lineno}: {line.strip()}")
    return hits


class TestDocsCarryNoPinnedTags(unittest.TestCase):
    def test_no_pinned_marketplace_ref(self) -> None:
        hits = _offenders(PINNED_MARKETPLACE)
        self.assertEqual(
            hits,
            [],
            "Install docs must not pin the marketplace ref to a tag -- the installed "
            "version comes from the plugin's own manifest, and a written-down tag only "
            "goes stale. Use `/plugin marketplace add deagy/cadre`.\n"
            + "\n".join(hits),
        )

    def test_no_pinned_clone_ref(self) -> None:
        hits = _offenders(PINNED_CLONE)
        self.assertEqual(
            hits,
            [],
            "Install docs must not clone at a hardcoded tag; use a plain `git clone`.\n"
            + "\n".join(hits),
        )


class TestKernelVersionProseMatchesProvider(unittest.TestCase):
    def test_quoted_kernel_version_matches_provider_manifest(self) -> None:
        manifest = json.loads(
            (REPOSITORY_ROOT / "provider" / "provider.json").read_text(encoding="utf-8")
        )
        minimum = manifest["kernel_compatibility"]["minimum"]
        supported_series = ".".join(minimum.split(".")[:2])

        mismatches = []
        for path in markdown_files():
            text = _strip_history_blocks(path.read_text(encoding="utf-8"))
            for lineno, line in enumerate(text.splitlines(), start=1):
                for found in KERNEL_VERSION_PROSE.findall(line):
                    if found != supported_series:
                        mismatches.append(
                            f"{path.relative_to(REPOSITORY_ROOT)}:{lineno}: "
                            f"quotes v{found}, expected v{supported_series}"
                        )

        self.assertEqual(
            mismatches,
            [],
            "Prose quoting an Agentic SDLC kernel version must agree with "
            f"provider/provider.json's kernel_compatibility.minimum ({minimum}). Note "
            "that manifest's own `version` field is a different version line -- quoting "
            "it here is the exact bug this guards.\n" + "\n".join(mismatches),
        )


if __name__ == "__main__":
    unittest.main()
