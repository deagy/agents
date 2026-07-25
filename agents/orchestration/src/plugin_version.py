#!/usr/bin/env python3
"""Read, check, or set the packaged plugin's release version.

The packaged plugin at ``plugins/secure-cloud-agents/`` declares its own
version independently in two manifests: ``.claude-plugin/plugin.json`` (Claude
Code) and ``.codex-plugin/plugin.json`` (Codex CLI). Both must always agree,
and should track this repository's release tags (``vMAJOR.MINOR.PATCH``) one
for one. Neither `agents generate-plugin` nor any other regeneration step
writes this field — it is intentionally hand-set only through this tool, so a
release is always a deliberate, reviewed action.

    agents version                    # print the current, verified version
    agents version --check            # exit non-zero if unset/mismatched/invalid
    agents version --set 0.3.0        # write a new version into both manifests

This does not create a git tag or push anything; see the "Releasing" section
of README.md for the full release flow. `.github/workflows/release.yml` tags
and publishes automatically once a version bump like this lands on `main`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ORCHESTRATION_ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = ORCHESTRATION_ROOT.parent
REPOSITORY_ROOT = AGENTS_ROOT.parent
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "secure-cloud-agents"

MANIFESTS = {
    "claude": PLUGIN_ROOT / ".claude-plugin" / "plugin.json",
    "codex": PLUGIN_ROOT / ".codex-plugin" / "plugin.json",
}

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def is_semver(value: str) -> bool:
    return bool(SEMVER_PATTERN.match(value))


def read_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name, path in MANIFESTS.items():
        if not path.is_file():
            raise SystemExit(f"agents version: missing manifest {path}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if "version" not in manifest:
            raise SystemExit(f"agents version: {path} has no \"version\" field")
        versions[name] = manifest["version"]
    return versions


def check_versions() -> list[str]:
    problems: list[str] = []
    versions = read_versions()
    for name, version in versions.items():
        if not is_semver(version):
            problems.append(f"{MANIFESTS[name]}: {version!r} is not MAJOR.MINOR.PATCH semver")
    distinct = set(versions.values())
    if len(distinct) > 1:
        rendered = ", ".join(f"{name}={version}" for name, version in sorted(versions.items()))
        problems.append(f"plugin manifests disagree on version: {rendered}")
    return problems


# Line-based, not JSON-structure-aware: matches the first line naming a
# top-level-shaped "version" key. set_version() below always re-parses the
# result and checks it against the intended value before accepting it, so a
# manifest shape this pattern can't handle correctly fails loudly instead of
# writing wrong content — do not remove that check as "redundant."
VERSION_LINE_PATTERN = re.compile(r'^(\s*"version"\s*:\s*")[^"]*(",?\s*)$', re.MULTILINE)


def set_version(version: str) -> None:
    if not is_semver(version):
        raise SystemExit(f"agents version: {version!r} is not MAJOR.MINOR.PATCH semver")

    # Build and validate every manifest's new content before writing any of
    # them, so a problem with one manifest can never leave a different one
    # already rewritten on disk — the two must change together or not at all.
    updates: dict[Path, str] = {}
    for path in MANIFESTS.values():
        original = path.read_text(encoding="utf-8")
        updated, count = VERSION_LINE_PATTERN.subn(rf"\g<1>{version}\g<2>", original, count=1)
        if count != 1:
            raise SystemExit(f"agents version: could not locate a \"version\" line in {path}")
        # Re-parse to confirm the substitution kept the file valid JSON with the intended value.
        if json.loads(updated).get("version") != version:
            raise SystemExit(f"agents version: substitution produced unexpected JSON in {path}")
        updates[path] = updated

    for path, updated in updates.items():
        path.write_text(updated, encoding="utf-8")


def _print_current_version_or_fail() -> int:
    problems = check_versions()
    if problems:
        for problem in problems:
            print(f"agents version: {problem}", file=sys.stderr)
        return 1
    versions = read_versions()
    print(next(iter(versions.values())))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verify the manifests agree on a valid semver version")
    group.add_argument("--set", metavar="VERSION", help="write VERSION (MAJOR.MINOR.PATCH) into both manifests")
    arguments = parser.parse_args()

    if arguments.set is not None:
        set_version(arguments.set)
        print(f"agents version: set to {arguments.set}")
        return 0

    # Bare invocation and --check are deliberately the same: read-and-verify,
    # printing the version on success. --check exists as a self-documenting,
    # explicit flag for CI (see .github/workflows/release.yml).
    return _print_current_version_or_fail()


if __name__ == "__main__":
    raise SystemExit(main())
