#!/usr/bin/env python3
"""Safely install the suite's namespaced Codex role wrappers."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROVENANCE_MARKER = "# GENERATED FILE: canonical source is agents/"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = REPOSITORY_ROOT / "plugins" / "secure-cloud-agents" / "codex-agents"


def sync_wrappers(source: Path, target: Path) -> dict[str, list[str]]:
    wrappers = sorted(source.glob("secure-cloud-agents-*.toml"))
    if not wrappers:
        raise ValueError(f"No namespaced Codex wrappers found under {source}")

    collisions = []
    for wrapper in wrappers:
        if wrapper.is_symlink() or not wrapper.is_file():
            raise RuntimeError(f"Refusing non-regular source wrapper: {wrapper}")
        destination = target / wrapper.name
        destination_exists = destination.exists() or destination.is_symlink()
        owned = (
            destination.is_file()
            and not destination.is_symlink()
            and PROVENANCE_MARKER
            in destination.read_text(encoding="utf-8", errors="replace")
        )
        if destination_exists and not owned:
            collisions.append(str(destination))
    if collisions:
        raise RuntimeError(
            "Refusing to overwrite unowned namespaced Codex wrapper(s): "
            + ", ".join(collisions)
        )

    target.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    unchanged: list[str] = []
    for wrapper in wrappers:
        destination = target / wrapper.name
        if destination.is_file() and destination.read_bytes() == wrapper.read_bytes():
            unchanged.append(str(destination))
            continue
        shutil.copyfile(wrapper, destination)
        installed.append(str(destination))
    return {"installed": installed, "unchanged": unchanged}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install namespaced Secure Cloud Agents Codex wrappers without touching bare role files.",
        allow_abbrev=False,
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=Path.home() / ".codex" / "agents")
    options = parser.parse_args()
    result = sync_wrappers(options.source.resolve(), options.target.expanduser().resolve())
    print(f"Installed {len(result['installed'])}; unchanged {len(result['unchanged'])}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"agents: {error}", file=sys.stderr)
        raise SystemExit(1) from error
