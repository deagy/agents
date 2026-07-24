"""Read versioned lifecycle contracts through the standalone Agentic SDLC CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def lifecycle_contract() -> dict[str, Any]:
    executable = os.environ.get("AGENTIC_SDLC_BIN") or shutil.which("agentic-sdlc")
    if not executable:
        raise RuntimeError(
            "Agentic SDLC v0.2.x is required; set AGENTIC_SDLC_BIN or install "
            "https://github.com/deagy/agentic-sdlc"
        )
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
