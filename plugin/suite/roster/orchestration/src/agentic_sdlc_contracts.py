"""Read versioned lifecycle contracts through the standalone Agentic SDLC CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_SRC_DIR = Path(__file__).resolve().parent
_SHARED_SRC_DIR = _SRC_DIR.parent.parent / "shared" / "src"
if str(_SHARED_SRC_DIR) not in sys.path:
    sys.path.append(str(_SHARED_SRC_DIR))

import settings  # noqa: E402  (sys.path set above)

_PROVIDER_MANIFEST = _SRC_DIR.parent.parent.parent / "provider" / "provider.json"


def kernel_requirement() -> str:
    """The supported kernel version range, as prose, read from provider.json.

    Never hardcode this. `provider.json` carries *two* unrelated version
    lines -- its own `version` (the provider-manifest version, currently
    0.3.x) and `kernel_compatibility` (the Agentic SDLC kernel range,
    currently 0.13.0+). Every install message in this repository used to
    quote the former while meaning the latter, which sent operators to a
    kernel ten minor versions too old.
    """
    try:
        manifest = json.loads(_PROVIDER_MANIFEST.read_text(encoding="utf-8"))
        compatibility = manifest["kernel_compatibility"]
        return f"v{compatibility['minimum']} or newer (below v{compatibility['maximum_exclusive']})"
    except (OSError, ValueError, KeyError, TypeError):
        # The manifest is optional context for an error message; never let
        # reading it turn a "kernel missing" diagnostic into a traceback.
        return "a compatible version"


def install_message() -> str:
    return (
        f"Agentic SDLC {kernel_requirement()} is required; set AGENTIC_SDLC_BIN "
        "or install https://github.com/deagy/agentic-sdlc"
    )


CONTRACT_TIMEOUT_SECONDS = 10
SUPPORTED_LIFECYCLE_CONTRACT_VERSION = 2


def _resolve_executable() -> str | None:
    """The single implementation of this resolution -- env var >
    project-local/user-global `agentic_sdlc.bin_path` config (global-only
    scope: this selects an executable, so a project-local file can never
    set it) > `shutil.which("agentic-sdlc")` as the computed default.
    `generate_global_plugin.py` reuses this function rather than
    duplicating the expression."""
    return settings.resolve_optional("agentic_sdlc.bin_path")


@lru_cache(maxsize=1)
def _fetch_contract(executable: str) -> dict[str, Any]:
    result = subprocess.run(
        [executable, "show-contract", "lifecycle-gates"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=CONTRACT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Agentic SDLC contract lookup failed: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Agentic SDLC returned malformed JSON for lifecycle-gates") from error
    if not isinstance(value, dict) or not isinstance(value.get("gates"), list):
        raise RuntimeError("Agentic SDLC returned an invalid lifecycle-gates contract")
    if value.get("version") != SUPPORTED_LIFECYCLE_CONTRACT_VERSION:
        raise RuntimeError(
            "Agentic SDLC returned an incompatible lifecycle-gates contract "
            f"(expected version {SUPPORTED_LIFECYCLE_CONTRACT_VERSION}, got {value.get('version')!r})"
        )
    return value


def try_lifecycle_contract() -> dict[str, Any] | None:
    """Return the lifecycle-gates contract, or None if Agentic SDLC isn't
    available.

    Exception: may raise `settings.SettingsError` (specifically
    `SettingsScopeError`) if a project-local `.agents/cadre.yaml`/`.json`
    sets `agentic_sdlc.bin_path` -- that field is global-only, since a
    project-local file is untrusted, clonable content and this value
    selects an executable to spawn. That is a security event, not an
    "unavailable" outcome, and must not be swallowed into None; callers
    (`cadre select` via `select_agents.py`'s top-level handler, `cadre
    sdlc` via `bin/cadre.py`'s `dispatch_sdlc`) catch `SettingsError`
    explicitly and surface a clean error instead of a bare traceback.
    """
    executable = _resolve_executable()
    if not executable:
        return None
    return _load_contract(executable)


def _load_contract(executable: str) -> dict[str, Any]:
    try:
        return _fetch_contract(executable)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Agentic SDLC contract lookup timed out after {CONTRACT_TIMEOUT_SECONDS} seconds: {executable}"
        ) from error
    except OSError as error:
        raise RuntimeError(f"Agentic SDLC contract lookup could not execute {executable}: {error}") from error


def require_lifecycle_contract() -> dict[str, Any]:
    """Return the lifecycle-gates contract, raising if Agentic SDLC isn't available."""
    executable = _resolve_executable()
    if not executable:
        raise RuntimeError(install_message())
    return _load_contract(executable)
