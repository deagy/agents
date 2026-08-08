#!/usr/bin/env python3
"""Guard against docs telling anyone to *use* a repository that was archived
by the monorepo merge.

Four repositories were merged into `deagy/cadre` and archived:
`deagy/cadre-lifecycle` (-> `plugin/`), `deagy/agentic-sdlc` (-> `kernel/`,
`engine/`), `deagy/cadre-plugin` (an earlier plugin repo), and
`deagy/cadre-profile-secure-cloud`. An archived repository stays cloneable
and its URLs keep resolving, so every stale instruction still *works* -- it
just silently delivers frozen content. Nothing failed; readers were simply
sent somewhere that would never update again.

That is exactly how the references survived the merge. They were found by a
documentation review months later, in the README, RUNBOOK, AGENTS.md, both
Cline plugin READMEs, a skill, a generator's `--output is required` error
message, and `kernel/pyproject.toml`'s `Repository` field -- the last of
which broke SECURITY.md's own `pip show` provenance check, since it told
readers to verify a homepage the package did not declare. A later sweep
still missed one in `plugin/CHANGELOG.md`'s header, above the first version
heading. Five rounds, five misses.

## Why this bans instructions rather than the names

The archived names appear ~150 times in this repository and most of those
are correct: provenance records ("before the monorepo merge it was
`deagy/cadre-lifecycle`"), CHANGELOG entries describing the arrangement at
the time, migration docs, and design proposals. Banning the name would make
this test unusable and it would be deleted.

So the patterns below match only *actionable* references -- a command to
run, a path to write to, or a URL a reader is meant to open. Prose that
merely names an archived repository is fine and stays fine.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ARCHIVED = r"(?:cadre-lifecycle|agentic-sdlc|cadre-plugin|cadre-profile-secure-cloud)"

# Each entry: (regex, what a reader would wrongly do). The regexes intentionally
# require an *action* -- a command verb, an --output/-o target, an install
# spec, or a browsable URL path -- so that naming an archived repo in prose
# never trips this.
FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(rf"git\s+clone\s+\S*github\.com/deagy/{ARCHIVED}"),
        "clone an archived repository",
    ),
    (
        re.compile(rf"(?:/plugin|codex\s+plugin|cline\s+plugin)[^\n]*\bdeagy/{ARCHIVED}\b"),
        "install from an archived marketplace/repository",
    ),
    (
        re.compile(rf"pipx?\s+install[^\n]*deagy/{ARCHIVED}"),
        "pip/pipx install from an archived repository",
    ),
    (
        re.compile(rf"--output\s+\S*{ARCHIVED}"),
        "generate output into a checkout of an archived repository",
    ),
    (
        re.compile(rf"github\.com/deagy/{ARCHIVED}/(?:releases|tree|blob|issues|security)"),
        "browse a page in an archived repository",
    ),
    (
        re.compile(rf"^\s*Repository\s*=\s*\"[^\"]*deagy/{ARCHIVED}\"", re.MULTILINE),
        "declare package metadata pointing at an archived repository",
    ),
]

# Files whose whole purpose is recording the pre-merge arrangement. These may
# contain otherwise-forbidden strings, because rewriting a historical record to
# describe the present would falsify it. Keep this list short and specific --
# a directory is not an acceptable entry, because it would exempt future files
# nobody reviewed.
HISTORICAL_RECORDS = {
    # Both changelogs quote install commands exactly as they were at the time
    # of each entry. Rewriting a released version's notes to name a repository
    # that did not host it yet would falsify the record.
    "CHANGELOG.md",
    "plugin/CHANGELOG.md",
}

SCANNED_SUFFIXES = {".md", ".py", ".toml", ".json", ".yml", ".yaml", ".ts", ".sh", ".ps1"}

# Line-level opt-out for a historical reference inside an otherwise-live file
# -- quoting the old marketplace string as the example of a bug a test exists
# to prevent, say. Put `archived-ref-ok: <reason>` on the offending line or the
# one above it. Exempting the whole file would be wrong here: these files are
# actively edited, and a file-level pass would silently cover a *future*
# instruction added to them.
OPT_OUT = re.compile(r"archived-ref-ok:\s*(\S.*)")


def tracked_files() -> list[Path]:
    """Git-tracked files only -- untracked scratch and ignored build output are
    not this test's business, and `node_modules` alone would dominate the scan."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return [
        REPO_ROOT / name
        for name in result.stdout.split("\0")
        if name and Path(name).suffix in SCANNED_SUFFIXES
    ]


class ArchivedRepositoryReferenceTests(unittest.TestCase):
    def test_no_actionable_reference_to_an_archived_repository(self) -> None:
        findings: list[str] = []
        for path in tracked_files():
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative in HISTORICAL_RECORDS:
                continue
            # A generated copy of an exempt file inherits its exemption --
            # `plugin/suite/` mirrors docs wholesale, so re-listing each one
            # would be noise that drifts the moment a doc is renamed.
            if relative.startswith("plugin/suite/") and relative.removeprefix(
                "plugin/suite/"
            ) in HISTORICAL_RECORDS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lines = text.splitlines()
            for pattern, consequence in FORBIDDEN_PATTERNS:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    # The marker may sit on the offending line or the one above
                    # it, so a long line can carry its justification separately.
                    context = lines[max(0, line - 2) : line]
                    if any(OPT_OUT.search(candidate) for candidate in context):
                        continue
                    findings.append(
                        f"{relative}:{line}: tells a reader to {consequence}\n"
                        f"    {match.group().strip()[:110]}"
                    )
        self.assertEqual(
            [],
            findings,
            "Instructions pointing at an archived repository. These still "
            "'work' -- an archived repo stays cloneable -- so they fail "
            "silently by serving frozen content. Point at deagy/cadre and the "
            "in-tree plugin/, kernel/, or engine/ instead. If the reference is "
            "a deliberate historical record, add the file to "
            "HISTORICAL_RECORDS with that justification.\n\n" + "\n".join(findings),
        )

    def test_historical_record_exemptions_are_still_needed(self) -> None:
        """An exemption for a file that no longer trips any pattern is a
        standing hole: it would silently exempt that file's *future* content."""
        for relative in sorted(HISTORICAL_RECORDS):
            with self.subTest(path=relative):
                path = REPO_ROOT / relative
                self.assertTrue(path.is_file(), f"exempt file does not exist: {relative}")
                text = path.read_text(encoding="utf-8")
                self.assertTrue(
                    any(pattern.search(text) for pattern, _ in FORBIDDEN_PATTERNS),
                    f"{relative} is exempt but no longer contains any forbidden "
                    f"pattern -- remove it from HISTORICAL_RECORDS so the file "
                    f"is checked again",
                )


if __name__ == "__main__":
    unittest.main()
