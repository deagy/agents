#!/usr/bin/env python3
"""A freshly generated plugin distribution, built once per test process.

Before the monorepo merge, the generated distribution (`agents/`, `skills/`,
`suite/`, `agent-catalog.json`, `bin/cadre`, `provider.json`, `profiles/`,
`extensions/` -- about 340 files) was *committed* into deagy/cadre-lifecycle
and kept in sync with the register by `cadre-ref.txt`, `drift-check.yml`,
and `regenerate.yml`. Tests here could therefore read it straight off disk.

The merge deleted that arrangement: there is now exactly one copy of every
role, skill, and provider file, and the distribution is a build artifact
written into a gitignored `/plugin-dist/`. Tests that assert on what the
*generator produces* have to produce it first, which is what this module
does. `roster/orchestration/test/test_repository_health.py` has used this
same build-once-and-reuse approach all along; this is the plugin-side
counterpart of it.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "roster" / "orchestration" / "src" / "generate_global_plugin.py"

_CACHED: Path | None = None


def generated_package() -> Path:
    """Build the plugin distribution into a temp dir, once, and return it."""
    global _CACHED
    if _CACHED is None:
        directory = Path(tempfile.mkdtemp(prefix="cadre-plugin-dist-"))
        atexit.register(shutil.rmtree, directory, True)
        target = directory / "cadre-plugin"
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--output", str(target)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"generate-plugin failed ({result.returncode}):\n{result.stderr or result.stdout}"
            )
        _CACHED = target
    return _CACHED
