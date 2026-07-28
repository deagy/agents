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

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_global_plugin import GENERATED_MARKER  # noqa: E402
from routing import parse_keyed_entries  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUTHORITY_ROOT = REPOSITORY_ROOT / "agents" / "authority"
DATA_PATH = AUTHORITY_ROOT / "aides.yaml"
TEMPLATE_PATH = AUTHORITY_ROOT / "_template.md.tmpl"
REQUIRED_FIELDS = ("title", "gates")


def _strip_inline_comment(value: str) -> str:
    # A '#' only starts a comment when preceded by whitespace (or at the start
    # of the line) so values that legitimately contain '#' (e.g. "C# Lead")
    # are left intact.
    return re.sub(r"(?:^|\s)#.*$", "", value).strip()


def _parse_gates(path: Path, aide_id: str, raw: str) -> list[int]:
    value = _strip_inline_comment(raw)
    if not (value.startswith("[") and value.endswith("]")):
        raise ValueError(
            f"{path}: aide {aide_id!r} gates must be a flow-style list like '[1, 2]', got {value!r}"
        )
    raw_items = [part.strip() for part in value[1:-1].split(",") if part.strip()]
    if not raw_items:
        raise ValueError(f"{path}: aide {aide_id!r} has an empty gates list")
    try:
        return [int(part) for part in raw_items]
    except ValueError as error:
        raise ValueError(f"{path}: aide {aide_id!r} has a non-integer gate in {value!r}") from error


def load_aides(path: Path) -> list[dict[str, object]]:
    """Parse aides.yaml's `<id>: {title, gates}` blocks.

    Reuses routing.py's parse_keyed_entries(), the same 2-space-id /
    4-space-field parser catalog.yaml is read with, so this table and
    catalog.yaml are never parsed by two independently hand-rolled
    implementations of the same shape. Field order within an entry does not
    matter.
    """
    raw_entries = parse_keyed_entries(path.read_text(encoding="utf-8"), REQUIRED_FIELDS)
    aides: list[dict[str, object]] = []
    for aide_id, fields in raw_entries.items():
        missing = [field for field in REQUIRED_FIELDS if field not in fields]
        if missing:
            raise ValueError(f"{path}: aide {aide_id!r} is missing required field(s): {', '.join(missing)}")
        aides.append(
            {
                "id": aide_id,
                "title": _strip_inline_comment(fields["title"]),
                "gates": _parse_gates(path, aide_id, fields["gates"]),
            }
        )
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
    body = template.format(
        title=aide["title"],
        gate_phrase=gate_phrase(gates),
        gate_list=gate_list(gates),
    )
    return f"{GENERATED_MARKER}\n\n{body}"


def generate(aides: list[dict[str, object]], template: str) -> dict[Path, str]:
    return {
        AUTHORITY_ROOT / str(aide["id"]) / "AGENT.md": render(template, aide)
        for aide in aides
    }


def existing_generated_files() -> set[Path]:
    return set(AUTHORITY_ROOT.glob("*-aide/AGENT.md"))


def main() -> int:
    aides = load_aides(DATA_PATH)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = generate(aides, template)
    orphaned = existing_generated_files() - set(rendered)

    if "--check" in sys.argv[1:]:
        stale = [
            str(path.relative_to(REPOSITORY_ROOT))
            for path, content in rendered.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != content
        ]
        stale.extend(str(path.relative_to(REPOSITORY_ROOT)) for path in orphaned)
        if stale:
            print(
                "Authority-aide AGENT.md files are stale; run "
                "agents/orchestration/src/generate_authority_aides.py: " + ", ".join(sorted(stale)),
                file=sys.stderr,
            )
            return 1
        print(f"{len(rendered)} authority-aide AGENT.md files are current")
        return 0

    for path in orphaned:
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
    for path, content in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"Generated {len(rendered)} authority-aide AGENT.md files under {AUTHORITY_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
