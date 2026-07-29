#!/usr/bin/env python3
"""Strict, standalone JSON Schema validation for
`agents/runner-capabilities.json` (idea #8, REQ-CADRE-BACKLOG-8).

This is the schema-shape half of idea #8's fail-closed contract (CM-NFR-5),
complementary to -- not a replacement for -- the structural guarantee that
already exists in `agents/orchestration/src/generate_global_plugin.py`:
`CAPABILITY_PROFILES`/`ALLOWED_MODELS`/`ALLOWED_CODEX_MODELS`/
`ALLOWED_REASONING_EFFORTS` (and, via `generate_role_metadata.py`,
`TIER_MAP`) are derived directly from this manifest at import time, so those
Python constants can never independently drift from it -- there is no
generation step to forget to re-run for *that* class of drift. What this
module checks instead is the manifest's own shape/type/enum content in
isolation (matching `agents/catalog.schema.json`'s idea #10 precedent): is
`agents/runner-capabilities.json` itself well-formed, e.g. does every
capability tier declare `tools`/`sandbox_mode`, does every runner declare all
required structural facts, are enum values closed to the known set.

`jsonschema` is an already-approved, pinned CI dependency
(`.github/requirements-validation.lock`, the same one
`agents/orchestration/src/schema_validate.py` uses) but is not guaranteed to
be installed in every local sandbox -- callers that need an optional-
dependency guard (e.g. test modules) should probe for it themselves, the same
way `agents/orchestration/test/test_schema_validation.py` does. This module
is a leaf script, not imported by any required generator path
(`generate_global_plugin.py`/`generate_role_metadata.py` never import it), so
`cadre generate-plugin`/`cadre select` remain jsonschema-free.

Run:

    python3 agents/orchestration/src/validate_runner_capabilities.py

Validate deterministically without changing the working tree (same
convention as `generate_role_metadata.py --check` / `schema_validate.py`):

    python3 agents/orchestration/src/validate_runner_capabilities.py --check

Exits non-zero with every finding on stderr when the manifest is invalid;
exits zero with a summary line on stdout when it is clean. Never mutates
`agents/runner-capabilities.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "agents" / "runner-capabilities.json"
DEFAULT_SCHEMA = REPOSITORY_ROOT / "agents" / "runner-capabilities.schema.json"


def _format_error(error: jsonschema.exceptions.ValidationError) -> str:
    pointer = "$" + "".join(
        f"[{part!r}]" if isinstance(part, str) else f"[{part}]" for part in error.absolute_path
    )
    return f"{pointer}: {error.message}"


def validate(manifest: Any, schema: dict[str, Any]) -> list[str]:
    """Return a deterministic, ordered list of finding strings. Empty means
    the manifest is schema-valid."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(map(str, error.absolute_path)))
    return [_format_error(error) for error in errors]


def run(manifest_path: Path = DEFAULT_MANIFEST, schema_path: Path = DEFAULT_SCHEMA) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{manifest_path}: invalid JSON: {error}"]
    return [f"{manifest_path} {finding}" for finding in validate(manifest, schema)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2] if __doc__ else None)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--check", action="store_true", help="Alias for the default (non-mutating) behavior.")
    args = parser.parse_args(argv)

    findings = run(args.manifest, args.schema)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    print(f"schema validation passed: {args.manifest} is schema-valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
