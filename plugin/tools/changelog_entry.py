#!/usr/bin/env python3
"""Extract a single version's release notes from CHANGELOG.md.

Used by `.github/workflows/release.yml` to populate a GitHub Release's body
without duplicating this repository's changelog by hand in the workflow
file. CHANGELOG.md's format is enforced by this script, not just followed by
convention: each version section must start with a top-level heading in the
form

    ## [MAJOR.MINOR.PATCH](url) - YYYY-MM-DD

and runs until the next such heading or end of file. Anything else (a plain
heading with no link, a version that doesn't appear) is treated as "entry
not found" rather than guessed at, so a malformed or missing entry fails the
release instead of silently publishing an empty Release body.

    python3 tools/changelog_entry.py 0.2.4     # print v0.2.4's entry body to stdout
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = PACKAGE_ROOT / "CHANGELOG.md"

HEADING_PATTERN = re.compile(
    r"^## \[(?P<version>\d+\.\d+\.\d+)\]\([^)]+\) - \d{4}-\d{2}-\d{2}\s*$",
    re.MULTILINE,
)


def extract_entry(version: str, changelog_text: str) -> str:
    headings = list(HEADING_PATTERN.finditer(changelog_text))
    for index, match in enumerate(headings):
        if match.group("version") != version:
            continue
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog_text)
        return changelog_text[start:end].strip("\n") + "\n"
    raise SystemExit(f"changelog_entry: no CHANGELOG.md entry found for version {version}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: changelog_entry.py MAJOR.MINOR.PATCH")
    version = sys.argv[1]
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    sys.stdout.write(extract_entry(version, text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
