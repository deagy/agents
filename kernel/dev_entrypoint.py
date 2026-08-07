#!/usr/bin/env python3
"""Dev/CI entry point for running the checked-out `agentic_sdlc` package
in place, without installing it.

Used by `bin/agentic-sdlc` and `test/test_agentic_sdlc.py`'s CLI subprocess
tests -- never packaged (excluded from both the wheel and sdist; see
pyproject.toml's [tool.hatch.build] configs, neither of which lists this
file). Deliberately NOT `python3 -m agentic_sdlc`: `-m` puts the *caller's
current working directory* at sys.path[0], searched before any
PYTHONPATH-prepended entry, so a caller invoking `agentic-sdlc --root .`
from inside a target project that happens to contain its own top-level
`agentic_sdlc` name would silently shadow this package. A plain script
invocation instead puts *this file's own directory* at sys.path[0]
(CPython's default script behavior), which never depends on the caller's
cwd, so `sys.path.insert` below is redundant with that default but kept
explicit rather than relying on it silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentic_sdlc import main  # noqa: E402  (sys.path set above)

if __name__ == "__main__":
    raise SystemExit(main())
