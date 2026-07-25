"""Read versioned lifecycle contracts through the standalone Agentic SDLC CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from typing import Any

INSTALL_MESSAGE = (
    "Agentic SDLC v0.3.x is required; set AGENTIC_SDLC_BIN or install "
    "https://github.com/deagy/agentic-sdlc"
)


def _resolve_executable() -> str | None:
    return os.environ.get("AGENTIC_SDLC_BIN") or shutil.which("agentic-sdlc")


@lru_cache(maxsize=1)
def _fetch_contract(executable: str) -> dict[str, Any]:
    result = subprocess.run(
        [executable, "show-contract", "lifecycle-gates"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Agentic SDLC contract lookup failed: {result.stderr.strip()}")
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or not isinstance(value.get("gates"), list):
        raise RuntimeError("Agentic SDLC returned an invalid lifecycle-gates contract")
    return value


def try_lifecycle_contract() -> dict[str, Any] | None:
    """Return the lifecycle-gates contract, or None if Agentic SDLC isn't available."""
    executable = _resolve_executable()
    if not executable:
        return None
    try:
        return _fetch_contract(executable)
    except (RuntimeError, OSError, json.JSONDecodeError):
        return None


def require_lifecycle_contract() -> dict[str, Any]:
    """Return the lifecycle-gates contract, raising if Agentic SDLC isn't available."""
    executable = _resolve_executable()
    if not executable:
        raise RuntimeError(INSTALL_MESSAGE)
    return _fetch_contract(executable)
