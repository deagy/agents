"""Entry point for `python -m agentic_sdlc`, matching the installed
`agentic-sdlc` console script (see pyproject.toml's [project.scripts])."""

from __future__ import annotations

from . import main

if __name__ == "__main__":
    raise SystemExit(main())
