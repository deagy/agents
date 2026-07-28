#!/usr/bin/env python3
"""Regenerate the authority-aide AGENT.md files from a shared template.

The eight `agents/authority/*-aide/AGENT.md` role definitions differ only in
the human-authority title and the Agentic SDLC gate number(s) they prepare a
decision package for. Everything else — Inputs, Outputs, Required checks,
Escalate when, Completion criteria — is identical policy prose shared by the
whole family. Rather than hand-maintain eight near-duplicate files, this
script renders them from agents/authority/aides.yaml (the per-role data) and
agents/authority/_template.md.tmpl (the shared prose), the same
generate-then-check pattern used for the packaged plugin
(agents/orchestration/src/generate_global_plugin.py).

Regenerate after editing aides.yaml or the template:

    python3 agents/orchestration/src/generate_authority_aides.py

Validate deterministically without changing the working tree:

    python3 agents/orchestration/src/generate_authority_aides.py --check
"""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUTHORITY_ROOT = REPOSITORY_ROOT / "agents" / "authority"
DATA_PATH = AUTHORITY_ROOT / "aides.yaml"
TEMPLATE_PATH = AUTHORITY_ROOT / "_template.md.tmpl"


def load_aides(path: Path) -> list[dict[str, object]]:
    aides: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "aides:":
            continue
        if stripped.startswith("- id:"):
            if current is not None:
                aides.append(current)
            current = {"id": stripped.split(":", 1)[1].strip()}
        elif current is not None and stripped.startswith("title:"):
            current["title"] = stripped.split(":", 1)[1].strip()
        elif current is not None and stripped.startswith("gates:"):
            raw = stripped.split(":", 1)[1].strip().strip("[]")
            current["gates"] = [int(part.strip()) for part in raw.split(",")]
    if current is not None:
        aides.append(current)
    return aides


def gate_phrase(gates: list[int]) -> str:
    labels = [f"G{gate}" for gate in gates]
    if len(labels) == 1:
        return f"gate {labels[0]}"
    if len(labels) == 2:
        return f"gates {labels[0]} and {labels[1]}"
    return f"gates {', '.join(labels[:-1])}, and {labels[-1]}"


def gate_list(gates: list[int]) -> str:
    return ", ".join(f"G{gate}" for gate in gates)


def render(template: str, aide: dict[str, object]) -> str:
    gates = aide["gates"]
    assert isinstance(gates, list)
    return template.format(
        title=aide["title"],
        gate_phrase=gate_phrase(gates),
        gate_list=gate_list(gates),
    )


def generate(aides: list[dict[str, object]], template: str) -> dict[Path, str]:
    return {
        AUTHORITY_ROOT / str(aide["id"]) / "AGENT.md": render(template, aide)
        for aide in aides
    }


def main() -> int:
    aides = load_aides(DATA_PATH)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = generate(aides, template)

    if "--check" in sys.argv[1:]:
        stale = [
            str(path.relative_to(REPOSITORY_ROOT))
            for path, content in rendered.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != content
        ]
        if stale:
            print(
                "Authority-aide AGENT.md files are stale; run "
                "agents/orchestration/src/generate_authority_aides.py: " + ", ".join(stale),
                file=sys.stderr,
            )
            return 1
        print(f"{len(rendered)} authority-aide AGENT.md files are current")
        return 0

    for path, content in rendered.items():
        path.write_text(content, encoding="utf-8")
    print(f"Generated {len(rendered)} authority-aide AGENT.md files under {AUTHORITY_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
