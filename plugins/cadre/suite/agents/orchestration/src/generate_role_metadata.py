#!/usr/bin/env python3
"""Regenerate `agents/catalog.yaml` and `agents/orchestration/routing.yaml`'s
`knowledge_focus` block from role metadata.

This is the generator half of the frontmatter-based role-metadata format
(the parsing/rendering primitives live in `role_metadata.py`). It reads, for
every role, whichever of two sources currently holds that role's metadata:

- **Migrated** roles (an `AGENT.md` that starts with `---`-delimited
  frontmatter): every field comes from the frontmatter, with no fallback to
  a legacy `catalog.yaml`/`routing.yaml` entry -- a field missing from
  frontmatter is a hard error, never silently inherited.
- **Legacy** (not yet migrated) roles: metadata comes from today's
  `agents/catalog.yaml` entry plus `agents/orchestration/routing.yaml`'s
  `knowledge_focus` entry, exactly as read today.

`agents/catalog-order.txt` supplies the dispatch-precedence order both
generated files are built in, and is the source of truth for which role ids
exist at all -- see that file's own header comment.

As of this generator's introduction, zero roles have been migrated, so every
run reproduces `agents/catalog.yaml` and `agents/orchestration/routing.yaml`
byte-for-byte from their legacy sources; the generator only starts changing
either file once a role's `AGENT.md` actually gains frontmatter.

Regenerate after editing catalog-order.txt or a role's frontmatter:

    python3 agents/orchestration/src/generate_role_metadata.py

Validate deterministically without changing the working tree:

    python3 agents/orchestration/src/generate_role_metadata.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_global_plugin import (  # noqa: E402
    ALLOWED_CODEX_MODELS,
    ALLOWED_MODELS,
    ALLOWED_REASONING_EFFORTS,
    CAPABILITY_PROFILES,
)
from role_metadata import (  # noqa: E402
    is_migrated,
    parse_frontmatter,
    parse_order_file,
)
from routing import load_routing, parse_catalog_entries  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AGENTS_ROOT = REPOSITORY_ROOT / "agents"
DEFAULT_CATALOG = DEFAULT_AGENTS_ROOT / "catalog.yaml"
DEFAULT_ROUTING = DEFAULT_AGENTS_ROOT / "orchestration" / "routing.yaml"
DEFAULT_ORDER = DEFAULT_AGENTS_ROOT / "catalog-order.txt"
DEFAULT_HEADER_TEMPLATE = DEFAULT_AGENTS_ROOT / "_catalog_header.yaml.tmpl"

# Closed set observed in today's catalog.yaml -- see that file's `phase:`
# values. Not derived from CAPABILITY_PROFILES/ALLOWED_* because phase is a
# dispatch/reporting label, not a runner capability grant.
ALLOWED_PHASES = frozenset(
    {
        "planning",
        "design",
        "security",
        "build",
        "verify",
        "review",
        "release",
        "operations",
        "support",
        "document",
        "evidence",
        "knowledge",
        "authority",
    }
)

# model / codex_model / reasoning_effort must always agree with this mapping
# (catalog.yaml's own header comment documents the same three tiers). Fails
# closed with no exceptions -- confirmed by the Product Owner. Verified by
# hand against today's full 47-role catalog.yaml before this check was
# introduced: no deviations found (see the Wave 0 implementation report).
TIER_MAP: dict[str, tuple[str, str]] = {
    "opus": ("gpt-5.6-sol", "high"),
    "sonnet": ("gpt-5.6-terra", "medium"),
    "haiku": ("gpt-5.6-luna", "low"),
}

CATALOG_FIELD_ORDER = ("definition", "phase", "capability", "model", "codex_model", "reasoning_effort")

# Historic hand-authored comment that sits directly above the first
# `phase: authority` role block in today's catalog.yaml (lines 325-330,
# immediately before the `product-owner-aide:` block). It documents
# authority-aide policy, not any one role's metadata, so it does not belong
# in frontmatter -- it is reproduced here verbatim so a Wave 0 (zero
# migrations) run of this generator remains byte-identical to today's file.
# If product-owner-aide is ever migrated to frontmatter, or reordered ahead
# of another authority role in catalog-order.txt, this constant should move
# to prefix whichever role becomes the first `phase: authority` entry, or be
# turned into prose in a more durable location -- it is pinned to a specific
# id only because that is where it already lives today.
ROLE_PREFIX_COMMENTS: dict[str, str] = {
    "product-owner-aide": (
        "  # `phase: authority` roles below prepare the decision package a human\n"
        "  # lifecycle authority needs for their assigned gate(s); they never approve,\n"
        "  # recommend a disposition, or hold delegated authority themselves (see\n"
        "  # docs/proposals/human-authority-role-agents.md). All read_only/opus per the\n"
        "  # design doc's rationale: these support high-blast-radius, hard-to-reverse\n"
        "  # human judgment calls even though the aide itself only assembles evidence.\n"
    ),
}

KNOWLEDGE_FOCUS_ANCHOR = '  "knowledge_focus": {'


class RoleMetadataError(ValueError):
    """Raised for any role-metadata inconsistency; carries a message that
    names the offending role id and/or field and file, per the fail-closed
    contract this generator promises callers.
    """


def _validate_record(role_id: str, record: dict[str, str], source: str) -> None:
    phase = record.get("phase")
    if phase not in ALLOWED_PHASES:
        raise RoleMetadataError(
            f"role {role_id!r} ({source}): phase {phase!r} must be one of: "
            f"{', '.join(sorted(ALLOWED_PHASES))}"
        )
    capability = record.get("capability")
    if capability not in CAPABILITY_PROFILES:
        raise RoleMetadataError(
            f"role {role_id!r} ({source}): capability {capability!r} must be one of: "
            f"{', '.join(sorted(CAPABILITY_PROFILES))}"
        )
    model = record.get("model")
    if model not in ALLOWED_MODELS:
        raise RoleMetadataError(
            f"role {role_id!r} ({source}): model {model!r} must be one of: {', '.join(sorted(ALLOWED_MODELS))}"
        )
    codex_model = record.get("codex_model")
    if codex_model not in ALLOWED_CODEX_MODELS:
        raise RoleMetadataError(
            f"role {role_id!r} ({source}): codex_model {codex_model!r} must be one of: "
            f"{', '.join(sorted(ALLOWED_CODEX_MODELS))}"
        )
    reasoning_effort = record.get("reasoning_effort")
    if reasoning_effort not in ALLOWED_REASONING_EFFORTS:
        raise RoleMetadataError(
            f"role {role_id!r} ({source}): reasoning_effort {reasoning_effort!r} must be one of: "
            f"{', '.join(sorted(ALLOWED_REASONING_EFFORTS))}"
        )
    expected = TIER_MAP.get(model)
    if expected is not None and (codex_model, reasoning_effort) != expected:
        raise RoleMetadataError(
            f"role {role_id!r} ({source}): model {model!r} requires codex_model "
            f"{expected[0]!r} and reasoning_effort {expected[1]!r}, got codex_model "
            f"{codex_model!r} and reasoning_effort {reasoning_effort!r}"
        )
    knowledge_focus = record.get("knowledge_focus")
    if not knowledge_focus:
        raise RoleMetadataError(f"role {role_id!r} ({source}): knowledge_focus must be a non-empty string")


def load_order(order_path: Path) -> list[str]:
    return parse_order_file(order_path.read_text(encoding="utf-8"))


def build_role_model(
    agents_root: Path, catalog_path: Path, routing_path: Path, order_path: Path
) -> tuple[list[str], dict[str, dict[str, str]]]:
    """Merge legacy and (once they exist) migrated role metadata into a
    single `(order_ids, roles)` result, `roles` keyed by role id and holding
    `definition`/`phase`/`capability`/`model`/`codex_model`/
    `reasoning_effort`/`knowledge_focus`. Every cross-check is fail-closed
    and names the offending role id.
    """
    order_ids = load_order(order_path)
    order_set = set(order_ids)

    legacy_catalog = parse_catalog_entries(catalog_path.read_text(encoding="utf-8"))
    routing_config = load_routing(routing_path)
    knowledge_focus_legacy: dict[str, str] = routing_config.get("knowledge_focus", {})

    legacy_path_to_id: dict[str, str] = {}
    for legacy_id, fields in legacy_catalog.items():
        definition = fields.get("definition")
        if definition is None:
            continue
        if definition in legacy_path_to_id:
            raise RoleMetadataError(
                f"{catalog_path}: definition path {definition!r} is used by both "
                f"{legacy_path_to_id[definition]!r} and {legacy_id!r}"
            )
        legacy_path_to_id[definition] = legacy_id

    discovered: dict[str, tuple[bool, str]] = {}
    for path in sorted(agents_root.rglob("AGENT.md")):
        relative = path.relative_to(agents_root).as_posix()
        text = path.read_text(encoding="utf-8")
        discovered[relative] = (is_migrated(text), text)

    id_to_path: dict[str, str] = {}
    for relative, (migrated, text) in discovered.items():
        if migrated:
            fields, _body = parse_frontmatter(text)  # type: ignore[misc]
            role_id = fields.get("id")
            if not role_id:
                raise RoleMetadataError(f"{relative}: migrated role frontmatter is missing required field 'id'")
            stale_catalog_id = legacy_path_to_id.get(relative)
            if stale_catalog_id is not None and stale_catalog_id != role_id:
                raise RoleMetadataError(
                    f"{relative}: frontmatter id {role_id!r} does not match "
                    f"{catalog_path}'s existing key {stale_catalog_id!r} for this definition path"
                )
        else:
            role_id = legacy_path_to_id.get(relative)
            if role_id is None:
                raise RoleMetadataError(f"{relative}: unmigrated AGENT.md has no matching {catalog_path} entry")
        if role_id in id_to_path:
            raise RoleMetadataError(
                f"duplicate role id {role_id!r}: {id_to_path[role_id]!r} and {relative!r}"
            )
        id_to_path[role_id] = relative

    missing_files = [role_id for role_id in order_ids if role_id not in id_to_path]
    if missing_files:
        raise RoleMetadataError(
            f"{order_path}: role id(s) with no matching AGENT.md: {', '.join(missing_files)}"
        )
    extra_ids = sorted(set(id_to_path) - order_set)
    if extra_ids:
        raise RoleMetadataError(
            f"AGENT.md discovered for role id(s) not listed in {order_path}: {', '.join(extra_ids)}"
        )

    roles: dict[str, dict[str, str]] = {}
    for role_id in order_ids:
        relative = id_to_path[role_id]
        migrated, text = discovered[relative]
        if migrated:
            fields, _body = parse_frontmatter(text)  # type: ignore[misc]
            required = ("phase", "capability", "model", "codex_model", "reasoning_effort", "knowledge_focus")
            missing_fields = [field for field in required if field not in fields]
            if missing_fields:
                raise RoleMetadataError(
                    f"role {role_id!r} ({relative}): frontmatter is missing required field(s): "
                    + ", ".join(missing_fields)
                )
            record = {"definition": relative, **{field: fields[field] for field in required}}
            source = relative
        else:
            legacy_fields = legacy_catalog[role_id]
            knowledge_focus = knowledge_focus_legacy.get(role_id)
            if knowledge_focus is None:
                raise RoleMetadataError(
                    f"role {role_id!r} ({relative}): missing its {routing_path} knowledge_focus entry"
                )
            record = {
                "definition": legacy_fields.get("definition", relative),
                "phase": legacy_fields.get("phase", ""),
                "capability": legacy_fields.get("capability", ""),
                "model": legacy_fields.get("model", ""),
                "codex_model": legacy_fields.get("codex_model", ""),
                "reasoning_effort": legacy_fields.get("reasoning_effort", ""),
                "knowledge_focus": knowledge_focus,
            }
            source = str(catalog_path)
        _validate_record(role_id, record, source)
        roles[role_id] = record

    return order_ids, roles


def render_catalog(order_ids: list[str], roles: dict[str, dict[str, str]], header_template: str) -> str:
    parts = [header_template]
    for role_id in order_ids:
        parts.append(ROLE_PREFIX_COMMENTS.get(role_id, ""))
        record = roles[role_id]
        lines = [f"  {role_id}:"]
        lines.extend(f"    {field}: {record[field]}" for field in CATALOG_FIELD_ORDER)
        parts.append("\n".join(lines) + "\n")
    return "".join(parts)


def _find_knowledge_focus_block(original_text: str) -> tuple[int, int]:
    occurrences = [match.start() for match in re.finditer(re.escape(KNOWLEDGE_FOCUS_ANCHOR), original_text)]
    if len(occurrences) != 1:
        raise RoleMetadataError(
            f"expected exactly one {KNOWLEDGE_FOCUS_ANCHOR!r} anchor line in routing.yaml, "
            f"found {len(occurrences)}"
        )
    anchor_start = occurrences[0]
    open_brace_index = original_text.index("{", anchor_start)
    depth = 0
    in_string = False
    escape = False
    index = open_brace_index
    while index < len(original_text):
        character = original_text[index]
        if in_string:
            if escape:
                escape = False
            elif character == "\\":
                escape = True
            elif character == '"':
                in_string = False
        else:
            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return open_brace_index, index
        index += 1
    raise RoleMetadataError("could not find a matching closing '}' for the knowledge_focus block")


def splice_knowledge_focus(original_text: str, order_ids: list[str], roles: dict[str, dict[str, str]]) -> str:
    """Surgically replace only the `"knowledge_focus": { ... }` region of
    `original_text` (routing.yaml's raw source), leaving every other byte
    untouched.

    Row order within the rebuilt block preserves each already-present role
    id's existing position (so an unchanged role set reproduces the
    original bytes exactly, even though today's routing.yaml key order does
    not match catalog-order.txt's dispatch-precedence order -- the two
    orders are independent and this generator does not attempt to force
    them to match); any role id newly present in `roles` that was not
    already in the block is appended in catalog-order.txt order.
    """
    open_brace_index, close_brace_index = _find_knowledge_focus_block(original_text)
    original_focus = json.loads(original_text[open_brace_index : close_brace_index + 1])

    ordered_ids = [role_id for role_id in original_focus if role_id in roles]
    ordered_ids.extend(role_id for role_id in order_ids if role_id not in original_focus and role_id in roles)

    body_lines = []
    for position, role_id in enumerate(ordered_ids):
        comma = "," if position < len(ordered_ids) - 1 else ""
        # ensure_ascii=False: today's knowledge_focus prose is all-ASCII,
        # but future non-ASCII prose (e.g. an em dash) should render as the
        # literal character rather than being escaped to \uXXXX.
        value = json.dumps(roles[role_id]["knowledge_focus"], ensure_ascii=False)
        body_lines.append(f"    {json.dumps(role_id, ensure_ascii=False)}: {value}{comma}\n")
    new_block = KNOWLEDGE_FOCUS_ANCHOR + "\n" + "".join(body_lines) + "  }"

    before_region = original_text[: original_text.rindex(KNOWLEDGE_FOCUS_ANCHOR, 0, open_brace_index + 1)]
    after_region = original_text[close_brace_index + 1 :]
    spliced = before_region + new_block + after_region

    before = json.loads(original_text)
    after = json.loads(spliced)
    for key in before:
        if key == "knowledge_focus":
            continue
        if after.get(key) != before.get(key):
            raise RoleMetadataError(f"splice unexpectedly altered routing.yaml key {key!r}")
    if set(after.get("knowledge_focus", {})) != set(roles):
        raise RoleMetadataError("knowledge_focus id-set mismatch after splice")

    return spliced


def generate(
    agents_root: Path = DEFAULT_AGENTS_ROOT,
    catalog_path: Path = DEFAULT_CATALOG,
    routing_path: Path = DEFAULT_ROUTING,
    order_path: Path = DEFAULT_ORDER,
    header_template_path: Path = DEFAULT_HEADER_TEMPLATE,
) -> dict[Path, str]:
    order_ids, roles = build_role_model(agents_root, catalog_path, routing_path, order_path)
    header_template = header_template_path.read_text(encoding="utf-8")
    catalog_content = render_catalog(order_ids, roles, header_template)

    original_routing_text = routing_path.read_text(encoding="utf-8")
    routing_content = splice_knowledge_focus(original_routing_text, order_ids, roles)
    _validate_routing_content(routing_content)

    return {catalog_path: catalog_content, routing_path: routing_content}


def _validate_routing_content(text: str) -> None:
    """Validate spliced routing.yaml content with the real `load_routing()`
    before it is ever written, by round-tripping it through a temporary
    file rather than duplicating `load_routing`'s validation logic.
    """
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
        handle.write(text)
        temporary_path = Path(handle.name)
    try:
        load_routing(temporary_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2] if __doc__ else None)
    parser.add_argument("--agents-root", type=Path, default=DEFAULT_AGENTS_ROOT)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--routing", type=Path, default=DEFAULT_ROUTING)
    parser.add_argument("--order", type=Path, default=DEFAULT_ORDER)
    parser.add_argument("--header-template", type=Path, default=DEFAULT_HEADER_TEMPLATE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    rendered = generate(args.agents_root, args.catalog, args.routing, args.order, args.header_template)

    if args.check:
        stale = [
            str(path)
            for path, content in rendered.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != content
        ]
        if stale:
            print(
                "Role metadata derived files are stale; run "
                "agents/orchestration/src/generate_role_metadata.py: " + ", ".join(stale),
                file=sys.stderr,
            )
            return 1
        print(f"{len(rendered)} role metadata files are current")
        return 0

    changed = 0
    for path, content in rendered.items():
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.write_text(content, encoding="utf-8")
        changed += 1
    print(f"Generated {len(rendered)} role metadata file(s) ({changed} changed) under {args.agents_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
