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
import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = BIN_DIR.parent
SUBCOMMANDS_PATH = BIN_DIR / "subcommands.tsv"
SDLC_DESCRIPTION = "Delegated Agentic SDLC CLI"
PROVIDER_MANIFEST = REPO_ROOT / "provider" / "provider.json"


def sdlc_install_message() -> str:
    """Point at the kernel range `provider.json` actually declares.

    Read lazily, and only on the failure path, so the dispatcher stays a
    thin shim on every successful invocation. Do not hardcode a version
    here: provider.json's own `version` and its `kernel_compatibility` are
    different version lines, and quoting the wrong one sent operators to a
    kernel ten minor versions too old.
    """
    requirement = "a compatible version"
    try:
        import json

        compatibility = json.loads(PROVIDER_MANIFEST.read_text(encoding="utf-8"))["kernel_compatibility"]
        requirement = f"v{compatibility['minimum']} or newer (below v{compatibility['maximum_exclusive']})"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return (
        f"cadre: Agentic SDLC {requirement} is required; install it from "
        "https://github.com/deagy/agentic-sdlc"
    )

_SHARED_SRC_DIR = REPO_ROOT / "roster" / "shared" / "src"
if str(_SHARED_SRC_DIR) not in sys.path:
    sys.path.append(str(_SHARED_SRC_DIR))

import settings  # noqa: E402  (sys.path set above)

INTERACTIVE_FLAG = "--interactive"


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
    lines.append("")
    lines.append(
        f"`{INTERACTIVE_FLAG}`, given as the leading argument before the subcommand name (e.g. "
        f"`cadre {INTERACTIVE_FLAG} select ...`), opts the dispatched subcommand into "
        "roster/shared/src/settings.py's interactive configuration prompt (CADRE_INTERACTIVE=1, "
        "passed via an explicit subprocess env= rather than mutating this process's own "
        "environment) -- only honored when stdin/stdout are both a real terminal; a value entered "
        "is offered a write to the project-local or user-global cadre config file."
    )
    return "\n".join(lines)


def _child_env(interactive: bool) -> dict[str, str] | None:
    if not interactive:
        return None
    child_env = dict(os.environ)
    child_env["CADRE_INTERACTIVE"] = "1"
    return child_env


def dispatch_sdlc(rest: list[str], *, interactive: bool = False) -> int:
    try:
        sdlc_bin = settings.resolve_optional(
            "agentic_sdlc.bin_path", env=_child_env(interactive) or os.environ
        )
    except settings.SettingsError as error:
        # resolve_optional() only ever raises for a global_only scope
        # violation (an untrusted project-local file setting
        # agentic_sdlc.bin_path) -- that's a security event this dispatcher
        # must surface, not a bare traceback out of a thin CLI shim.
        print(f"cadre: {error}", file=sys.stderr)
        return 1
    if not sdlc_bin:
        print(sdlc_install_message(), file=sys.stderr)
        return 1
    provider = REPO_ROOT / "provider" / "provider.json"
    result = subprocess.run(
        [sdlc_bin, "--provider", str(provider), *rest], env=_child_env(interactive)
    )
    return result.returncode


def main(argv: list[str]) -> int:
    interactive = False
    if argv and argv[0] == INTERACTIVE_FLAG:
        interactive = True
        argv = argv[1:]

    subcommands = load_subcommands()
    command = argv[0] if argv else "help"
    rest = argv[1:]

    if command in ("help", "-h", "--help"):
        print(usage(subcommands))
        return 0

    if command == "sdlc":
        return dispatch_sdlc(rest, interactive=interactive)

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
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / script), *rest], env=_child_env(interactive)
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
