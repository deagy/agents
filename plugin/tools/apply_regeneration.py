#!/usr/bin/env python3
"""Apply a `cadre generate-plugin` scratch output into this checkout.

README.md's "Regenerating Assets" section documents the manual procedure
this mirrors: regenerate into a scratch directory (never this checkout
directly -- see CLAUDE.md's "Regeneration guard caveat"), then apply
everything the generator produces *except* README.md, which always needs
human review because this repository's own README differs from the
generator's default.

The generated-path list below is a hand-kept mirror of deagy/cadre's
generate_global_plugin.py GENERATED_TOP_LEVEL / GENERATED_NESTED_PATHS
constants (not imported directly -- that module is part of a package with
its own relative imports, and this script only needs the two path lists,
not the rest of the generator). If a future cadre change adds a new
generated top-level member, this script silently won't copy it and the
opened PR will simply be missing that change -- the PR review step is the
backstop, same as it already is for every other regeneration mismatch.

    python3 tools/apply_regeneration.py --generated /tmp/regen --target .
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Mirrors GENERATED_TOP_LEVEL in deagy/cadre's generate_global_plugin.py,
# minus "README.md" (never auto-applied) and with "bin" narrowed to the one
# file it actually generates (see that module's reset_generated_content()).
GENERATED_TOP_LEVEL_DIRS = ("skills", "agents", "suite")
GENERATED_TOP_LEVEL_FILES = ("bin/cadre",)
# The provider bundle (deagy/cadre's PROVIDER_BUNDLE), copied verbatim.
PROVIDER_BUNDLE = ("provider.json", "agent-catalog.json", "profiles", "extensions", "codex-agents")
# Mirrors GENERATED_NESTED_PATHS: generated content living inside an
# otherwise hand-authored plugin directory. Only this subtree is replaced;
# plugins/lifecycle/{.claude-plugin,.codex-plugin,tools} and the entirety of
# plugins/lifecycle-github/ and plugins/lifecycle-gitlab/ are never touched.
GENERATED_NESTED_DIRS = ("plugins/lifecycle/skills",)

EXCLUDED = ("README.md",)


def replace_path(src: Path, dst: Path) -> None:
    """Make dst match src exactly (src missing => dst removed)."""
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def apply_regeneration(generated: Path, target: Path) -> list[str]:
    applied: list[str] = []
    for relative in (*GENERATED_TOP_LEVEL_DIRS, *PROVIDER_BUNDLE, *GENERATED_NESTED_DIRS):
        assert relative not in EXCLUDED  # pragma: no cover - defends the constant lists themselves
        replace_path(generated / relative, target / relative)
        applied.append(relative)
    for relative in GENERATED_TOP_LEVEL_FILES:
        replace_path(generated / relative, target / relative)
        applied.append(relative)
    return sorted(applied)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", required=True, type=Path, help="Scratch dir from `cadre generate-plugin --output`")
    parser.add_argument("--target", required=True, type=Path, help="This repository's checkout root")
    args = parser.parse_args(argv)

    generated = args.generated.resolve()
    target = args.target.resolve()
    if not generated.is_dir():
        parser.error(f"--generated {generated} is not a directory")
    if not target.is_dir():
        parser.error(f"--target {target} is not a directory")

    applied = apply_regeneration(generated, target)
    print(f"Applied {len(applied)} generated path(s) into {target} (README.md excluded):")
    for relative in applied:
        print(f"  {relative}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
