#!/usr/bin/env python3
"""Install and configure the external Agentic SDLC kernel for this plugin.

`bin/cadre sdlc` shells out to a separately installed `agentic-sdlc`
executable and simply fails with an install pointer if one isn't already on
`PATH` (or `AGENTIC_SDLC_BIN`) -- by design, the kernel is never vendored
here (see `provider.json`'s `kernel_compatibility` and README's "Lifecycle
Governance with Agentic SDLC"). This script is the deliberate, opt-in
convenience step a human runs once to close that gap: it `pipx install`s the
kernel version this plugin's `provider.json` currently declares compatible,
then runs `agentic-sdlc init` against a target project using this plugin's
own `provider.json`.

It intentionally does *not* wire into `bin/cadre` as a subcommand.
`generate_global_plugin.py` (in the separate `deagy/cadre` register repo)
fully regenerates `bin/cadre` from scratch on every `cadre generate-plugin`
run -- see that generator's `GENERATED_TOP_LEVEL` -- so any hand-added case
there would be silently deleted on the next sync. `tools/` is not part of
that generated set (see `tools/plugin_version.py`, the existing precedent
for a hand-authored script invoked directly rather than through `bin/cadre`).

    python3 plugins/lifecycle/tools/bootstrap_sdlc.py                       # install (if needed) + configure this project
    python3 plugins/lifecycle/tools/bootstrap_sdlc.py --dry-run              # report what would happen, change nothing
    python3 plugins/lifecycle/tools/bootstrap_sdlc.py --skip-init             # install/verify the kernel only
    python3 plugins/lifecycle/tools/bootstrap_sdlc.py --root /path/to/project --profile secure-cloud

Never reinstalls over an existing `agentic-sdlc` the human already has on
`PATH` or pointed at via `AGENTIC_SDLC_BIN`, even if its version falls
outside this plugin's supported range -- it reports the mismatch and stops,
the same fail-closed posture as `bin/cadre sdlc` itself, rather than
guessing which install the human intended to keep.

This file is an intentional duplicate, not copy-paste debt:
`plugins/lifecycle/tools/bootstrap_sdlc.py` is the source, and
`plugins/lifecycle-github/tools/bootstrap_sdlc.py` and
`plugins/lifecycle-gitlab/tools/bootstrap_sdlc.py` are self-sufficiency
copies of it so each forge plugin needs no dependency on the others (see
AGENTS.md's plugin-split rationale). Keep all three in sync when editing;
only the four example-invocation lines above are expected to differ between
copies, and `tools/test_plugin_duplication_health.py` enforces exactly
that.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

# This script lives in this plugin's own tools/ directory, three
# directories below the repository root (core, github, and gitlab each
# carry their own copy -- see tools/test_plugin_duplication_health.py).
# provider.json itself is not duplicated: it stays a single shared file at
# the repository root (see cadre-ref.txt), referenced here by relative
# path, the same convention this repository's skills already use for
# reaching root-level shared content.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROVIDER_MANIFEST_PATH = REPO_ROOT / "provider.json"

# The kernel now ships from the monorepo; deagy/agentic-sdlc is archived.
AGENTIC_SDLC_GIT_URL = "https://github.com/deagy/cadre.git"
AGENTIC_SDLC_SUBDIRECTORY = "kernel"

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# Overridable so tests (and, in principle, a caller with an unusual
# environment) don't have to actually invoke pipx/agentic-sdlc as a subprocess.
_run = subprocess.run


def parse_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER_PATTERN.match(value)
    if not match:
        raise ValueError(f"{value!r} is not MAJOR.MINOR.PATCH semver")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def read_kernel_compatibility(manifest_path: Path = PROVIDER_MANIFEST_PATH) -> tuple[str, str]:
    if not manifest_path.is_file():
        raise SystemExit(f"bootstrap-sdlc: missing provider manifest {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    compatibility = manifest.get("kernel_compatibility")
    if not isinstance(compatibility, dict):
        raise SystemExit(f"bootstrap-sdlc: {manifest_path} has no \"kernel_compatibility\" object")
    minimum = compatibility.get("minimum")
    maximum_exclusive = compatibility.get("maximum_exclusive")
    if not isinstance(minimum, str) or not isinstance(maximum_exclusive, str):
        raise SystemExit(
            f"bootstrap-sdlc: {manifest_path} kernel_compatibility must declare "
            "string \"minimum\" and \"maximum_exclusive\" versions"
        )
    return minimum, maximum_exclusive


def version_in_range(version: str, minimum: str, maximum_exclusive: str) -> bool:
    return parse_semver(minimum) <= parse_semver(version) < parse_semver(maximum_exclusive)


def resolve_existing_binary(env: dict[str, str] | None = None) -> str | None:
    env = os.environ if env is None else env
    explicit = env.get("AGENTIC_SDLC_BIN")
    if explicit:
        return explicit
    return shutil.which("agentic-sdlc")


def binary_version(binary: str) -> str:
    result = _run([binary, "--version"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{binary} --version failed: {result.stderr.strip()}")
    return result.stdout.strip()


def pipx_install(ref: str) -> int:
    target = f"git+{AGENTIC_SDLC_GIT_URL}@v{ref}#subdirectory={AGENTIC_SDLC_SUBDIRECTORY}"
    print(f"bootstrap-sdlc: installing Agentic SDLC v{ref} via pipx ({target})")
    # Our own prints above are Python-buffered; pipx's subprocess writes to
    # the same inherited stdout fd directly, so without an explicit flush
    # here its output can appear before ours despite running after it.
    sys.stdout.flush()
    result = _run(["pipx", "install", target], check=False)
    return result.returncode


def build_init_command(sdlc_bin: str, args: argparse.Namespace) -> list[str]:
    command = [
        sdlc_bin,
        "--provider",
        str(PROVIDER_MANIFEST_PATH),
        "init",
        "--root",
        str(args.root),
    ]
    if args.profile is not None:
        command += ["--profile", args.profile]
    for extension in args.extension:
        command += ["--extension", extension]
    if args.project_id is not None:
        command += ["--project-id", args.project_id]
    if args.classification is not None:
        command += ["--classification", args.classification]
    if args.runner is not None:
        command += ["--runner", args.runner]
    if args.dry_run:
        command += ["--dry-run"]
    return command


def ensure_kernel(args: argparse.Namespace, env: dict[str, str] | None = None) -> tuple[int, str | None]:
    """Resolve, or install, a compatible `agentic-sdlc` binary.

    Returns (exit_code, binary_path). `binary_path` is None whenever no
    further step (init) should run -- either the run failed, or `--dry-run`
    means nothing was actually installed to run against.
    """
    minimum, maximum_exclusive = read_kernel_compatibility()
    existing = resolve_existing_binary(env)

    if existing:
        try:
            version = binary_version(existing)
        except (RuntimeError, OSError) as error:
            print(f"bootstrap-sdlc: could not verify existing install: {error}", file=sys.stderr)
            return 1, None
        if version_in_range(version, minimum, maximum_exclusive):
            print(f"bootstrap-sdlc: Agentic SDLC {version} already installed and compatible ({existing})")
            return 0, existing
        print(
            f"bootstrap-sdlc: installed Agentic SDLC {version} at {existing} is outside this "
            f"plugin's supported range [{minimum}, {maximum_exclusive}); not reinstalling "
            "automatically. Point AGENTIC_SDLC_BIN at a compatible install, or uninstall "
            f"{existing} and re-run this command.",
            file=sys.stderr,
        )
        return 1, None

    if shutil.which("pipx") is None:
        print(
            "bootstrap-sdlc: pipx not found. Install it "
            "(https://pipx.pypa.io/stable/installation/) and re-run, or install Agentic SDLC "
            "yourself and set AGENTIC_SDLC_BIN.",
            file=sys.stderr,
        )
        return 1, None

    if args.dry_run:
        target = f"git+{AGENTIC_SDLC_GIT_URL}@v{minimum}#subdirectory={AGENTIC_SDLC_SUBDIRECTORY}"
        print(f"bootstrap-sdlc: would run: pipx install {target}")
        return 0, None

    returncode = pipx_install(minimum)
    if returncode != 0:
        return returncode, None

    installed = resolve_existing_binary(env) or shutil.which("agentic-sdlc")
    if not installed:
        print(
            "bootstrap-sdlc: pipx install succeeded, but agentic-sdlc still isn't resolvable on "
            "PATH in this shell. Run `pipx ensurepath`, start a new shell, and re-run this "
            "command to finish configuring the project.",
            file=sys.stderr,
        )
        return 1, None
    return 0, installed


def bootstrap(args: argparse.Namespace, env: dict[str, str] | None = None) -> int:
    exit_code, sdlc_bin = ensure_kernel(args, env)
    if exit_code != 0:
        return exit_code

    if args.skip_init:
        return 0

    if sdlc_bin is None:
        # Either --dry-run (nothing to configure against yet) or the kernel
        # was just installed but isn't resolvable in this process -- either
        # way ensure_kernel() already reported the reason.
        return 0

    sys.stdout.flush()
    result = _run(build_init_command(sdlc_bin, args), check=False)
    return result.returncode


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Target project root (default: cwd)")
    parser.add_argument("--profile", help="Provider profile id; omit for kernel-only lifecycle operation")
    parser.add_argument("--extension", action="append", default=[], help="Enable an impact-profile extension by id (repeatable)")
    parser.add_argument("--project-id")
    parser.add_argument("--classification")
    parser.add_argument("--runner", choices=["codex", "claude", "both"])
    parser.add_argument("--skip-init", action="store_true", help="Install/verify the kernel only; do not configure a project")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without installing or writing anything")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return bootstrap(args)


if __name__ == "__main__":
    raise SystemExit(main())
