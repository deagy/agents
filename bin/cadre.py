#!/usr/bin/env python3
"""Subcommand dispatcher for this repository's `cadre` CLI.

bin/cadre (POSIX sh) and bin/cadre.ps1 (PowerShell) are thin, per-platform
shims whose only job is finding a Python 3.10+ interpreter and handing off to
this file — that part can't move into Python, since a plain shebang can't
probe multiple interpreter candidates and version-check them before any
Python code is safe to run. Everything past that (the subcommand table, the
`sdlc` delegation to the standalone Agentic SDLC kernel, usage text, and
dispatch) lives here once instead of being duplicated in both shell
languages.

Also runnable directly: `python bin/cadre.py <subcommand> [args...]`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = BIN_DIR.parent
SUBCOMMANDS_PATH = BIN_DIR / "subcommands.tsv"
SDLC_DESCRIPTION = "Delegated Agentic SDLC v0.3.x CLI"
SDLC_INSTALL_MESSAGE = (
    "cadre: Agentic SDLC v0.3.x is required; install it from https://github.com/deagy/agentic-sdlc"
)


def load_subcommands(path: Path = SUBCOMMANDS_PATH) -> list[tuple[str, str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        name, script, description = line.split("\t")
        rows.append((name, script, description))
    return rows


def usage(subcommands: list[tuple[str, str, str]]) -> str:
    lines = ["Usage: cadre <subcommand> [args...]", "", "Subcommands:"]
    for name, _script, description in subcommands:
        lines.append(f"  {name:<16} {description}")
    lines.append(f"  {'sdlc':<16} {SDLC_DESCRIPTION}")
    lines.append(f"  {'help':<16} Show this message")
    lines.append("")
    lines.append("Each subcommand's own --help documents its arguments, e.g. `cadre sdlc plan --help`.")
    return "\n".join(lines)


def dispatch_sdlc(rest: list[str]) -> int:
    sdlc_bin = os.environ.get("AGENTIC_SDLC_BIN") or shutil.which("agentic-sdlc")
    if not sdlc_bin:
        print(SDLC_INSTALL_MESSAGE, file=sys.stderr)
        return 1
    provider = REPO_ROOT / "plugins" / "cadre" / "provider.json"
    result = subprocess.run([sdlc_bin, "--provider", str(provider), *rest])
    return result.returncode


def main(argv: list[str]) -> int:
    subcommands = load_subcommands()
    command = argv[0] if argv else "help"
    rest = argv[1:]

    if command in ("help", "-h", "--help"):
        print(usage(subcommands))
        return 0

    if command == "sdlc":
        return dispatch_sdlc(rest)

    match = next((row for row in subcommands if row[0] == command), None)
    if match is None:
        print(f"cadre: unknown subcommand '{command}'", file=sys.stderr)
        print(usage(subcommands), file=sys.stderr)
        return 1

    _name, script, _description = match
    # subprocess.run, not os.execv: os.execv/os.spawnv join argv into a
    # command-line string without subprocess's list2cmdline quoting on
    # Windows, so any argument containing a space (e.g. --task "multi word
    # value") silently gets re-split by the child process. subprocess.run
    # quotes correctly on every platform this needs to run on.
    result = subprocess.run([sys.executable, str(REPO_ROOT / script), *rest])
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
