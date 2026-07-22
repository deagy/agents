#!/usr/bin/env python3
"""Regenerate plugins/secure-cloud-agents/: thin, absolute-path pointer files.

This plugin makes this repository's own skills and agent roles reachable from
any project directory once installed at global/user scope. Unlike the portable
plugins/agentic-sdlc kernel, this suite is a single fixed instance on this
machine, not something copied into other repositories, so every generated file
below embeds this checkout's absolute path rather than a relative one —
required because an installed plugin is cached by the runner and loses access
to sibling repository content outside its own directory (component *discovery*
is confined to the plugin root; the *prose* inside a discovered file is free to
reference any absolute path, which is what these pointers rely on).

Skills are handled identically for both runners: plugin-bundled under
plugins/secure-cloud-agents/skills/, discoverable once the plugin is installed
at global/user scope (see plugins/agentic-sdlc/contracts/runner-adapters.md).

Agent-role wrappers are NOT symmetric, because the two runners differ here:
- Claude Code supports plugin-bundled subagents, auto-discovered from the
  plugin's default agents/ directory (do NOT also declare an "agents" field in
  plugin.json for this — that field expects individual file paths, not a
  directory, and a bare directory string fails manifest validation), so the
  role wrappers go under plugins/secure-cloud-agents/agents/*.md and become
  global automatically when the plugin is installed at user scope.
- Codex CLI has no such mechanism — custom agents are only discovered from
  .codex/agents/ (project) or ~/.codex/agents/ (global) on disk, never from a
  plugin manifest. The *.toml wrappers are generated to the repo-tracked
  staging directory plugins/secure-cloud-agents/codex-agents/ instead; copying
  them into ~/.codex/agents/ is a separate, explicit step (see
  plugins/secure-cloud-agents/README.md) rather than something this script does
  on its own, since it would otherwise be writing outside the repository.

A generated bin/agents wrapper is included too: Claude Code auto-discovers a
plugin's bin/ directory onto the Bash tool's PATH for the duration of a session
(convention-based, no plugin.json field required), so an orchestrating Claude
Code agent gets `agents <subcommand>` for free once this plugin is installed,
without the human's own shell PATH being touched (that part stays manual — see
README.md "System-wide install"; no plugin can modify a user's shell profile).
Codex CLI has no equivalent bin/ auto-discovery, so this is a Claude-Code-only
convenience layered on top of the manual PATH setup, not a replacement for it.

A generated agent-catalog.json (id -> {phase, kind, definition-as-absolute-path})
is also included: plugins/agentic-sdlc/scripts/agentic_sdlc.py's
AGENT_CATALOG_SEARCH_PATH picks it up when this plugin sits alongside it, which
is what lets that portable kernel's "secure-cloud" profile bake real AGENT.md
content into a target project's generated wrappers instead of a generic stub —
see rich_agent_content() there. Every other profile ignores this file entirely.

Regenerate after adding/removing a role in agents/catalog.yaml or a skill under
.agents/skills/, or if this checkout is ever moved or renamed:

    agents generate-plugin

(bin/agents at the repository root; or `python3 agents/orchestration/src/generate_global_plugin.py`
directly if bin/agents isn't set up yet).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AGENTS_ROOT = REPOSITORY_ROOT / "agents"
SKILLS_ROOT = REPOSITORY_ROOT / ".agents" / "skills"
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "secure-cloud-agents"
SHARED_POLICIES = [
    "agents/shared/operating-principles.md",
    "agents/shared/team-profile.yaml",
    "agents/shared/technology-standards.md",
    "agents/shared/library-standards.yaml",
    "agents/shared/knowledge-use-policy.md",
    "agents/shared/agent-autonomy.yaml",
]
REGENERATE_NOTE = (
    "This absolute path is specific to this machine's checkout. If it moves, "
    "regenerate this plugin with `agents generate-plugin` (bin/agents at the "
    "repository root)."
)
ASK_HUMAN_RULE = (
    "You are a dispatched subagent: you cannot ask the human directly. If you "
    "reach a decision only a human can make, stop and return a clearly labeled "
    "blocking question in your result instead of guessing or proceeding."
)


def load_catalog(path: Path) -> dict[str, dict[str, str]]:
    agents: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^  ([a-z0-9-]+):\s*$", line)
        if match:
            current = match.group(1)
            agents[current] = {}
            continue
        if current and line.strip().startswith(("definition:", "phase:")):
            key, value = line.strip().split(":", 1)
            agents[current][key] = value.strip()
    if not agents:
        raise ValueError("No agents found in catalog.yaml")
    return agents


def load_skill_frontmatter(skill_file: Path) -> dict[str, str]:
    content = skill_file.read_text(encoding="utf-8")
    block = content.split("---", 2)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if re.match(r"^[a-z_]+:", line):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def toml_string(value: str) -> str:
    return json.dumps(value)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def generate_skill_pointers() -> list[Path]:
    written = []
    for skill_dir in sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        frontmatter = load_skill_frontmatter(skill_file)
        name = frontmatter["name"]
        target = PLUGIN_ROOT / "skills" / name / "SKILL.md"
        body = "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {frontmatter['description']}",
                "---",
                "",
                "Read and follow the full instructions in",
                f"`{skill_file}`. Do not duplicate or summarize them here —",
                "treat that file as authoritative.",
                "",
                REGENERATE_NOTE,
                "",
            ]
        )
        write(target, body)
        written.append(target)
    return written


def generate_agent_pointers(catalog: dict[str, dict[str, str]]) -> list[Path]:
    written = []
    for agent_id, metadata in sorted(catalog.items()):
        definition = metadata["definition"]
        phase = metadata.get("phase", "unknown")
        reviewer = definition.startswith("review/")
        definition_path = AGENTS_ROOT / definition
        shared_paths = [str(REPOSITORY_ROOT / relative) for relative in SHARED_POLICIES]
        description = f"Secure cloud agent suite role for the {phase} phase ({agent_id})."
        instructions = (
            f"Repository root: {REPOSITORY_ROOT}\n\n"
            f"Read and follow {definition_path}, plus {', '.join(shared_paths)}, "
            "then act as this role for the task you're given.\n\n"
            f"{ASK_HUMAN_RULE}\n\n{REGENERATE_NOTE}"
        )

        md_target = PLUGIN_ROOT / "agents" / f"{agent_id}.md"
        md_body = "\n".join(
            [
                "---",
                f"name: {agent_id}",
                f"description: {description}",
                f"tools: {'Read, Grep, Glob, Bash' if reviewer else 'Read, Grep, Glob, Bash, Edit, Write'}",
                "---",
                "",
                instructions,
                "",
            ]
        )
        write(md_target, md_body)
        written.append(md_target)

        # Codex has no plugin-bundled-agent mechanism; this is a repo-tracked
        # staging copy, not something Codex discovers directly (see module docstring).
        toml_target = PLUGIN_ROOT / "codex-agents" / f"{agent_id}.toml"
        toml_body = "\n".join(
            [
                f"name = {toml_string(agent_id)}",
                f"description = {toml_string(description)}",
                f"sandbox_mode = {toml_string('read-only' if reviewer else 'workspace-write')}",
                f"developer_instructions = {toml_string(instructions)}",
                "",
            ]
        )
        write(toml_target, toml_body)
        written.append(toml_target)
    return written


def derive_kind(definition: str) -> str:
    if definition.startswith("review/"):
        return "reviewer"
    if definition.startswith("support/"):
        return "support"
    if definition in {"documentation/evidence-curator/AGENT.md", "knowledge-store/AGENT.md"}:
        return "curator"
    return "author"


def generate_agent_catalog_export(catalog: dict[str, dict[str, str]]) -> Path:
    """Absolute-path catalog export consumed by plugins/agentic-sdlc's
    AGENT_CATALOG_SEARCH_PATH, so a project that opts into the "secure-cloud"
    portable profile gets real role content instead of the generic stub —
    see agentic_sdlc.py's rich_agent_content()."""
    agents = {
        agent_id: {
            "phase": metadata.get("phase", "unknown"),
            "kind": derive_kind(metadata["definition"]),
            "definition": str(AGENTS_ROOT / metadata["definition"]),
        }
        for agent_id, metadata in sorted(catalog.items())
    }
    target = PLUGIN_ROOT / "agent-catalog.json"
    write(target, json.dumps({"agents": agents}, indent=2) + "\n")
    return target


def generate_bin_wrapper() -> Path:
    real_wrapper = REPOSITORY_ROOT / "bin" / "agents"
    target = PLUGIN_ROOT / "bin" / "agents"
    body = "\n".join(
        [
            "#!/bin/sh",
            f"# {REGENERATE_NOTE}",
            f'exec "{real_wrapper}" "$@"',
            "",
        ]
    )
    write(target, body)
    target.chmod(0o755)
    return target


def main() -> int:
    catalog = load_catalog(AGENTS_ROOT / "catalog.yaml")
    written = generate_skill_pointers() + generate_agent_pointers(catalog) + [
        generate_bin_wrapper(),
        generate_agent_catalog_export(catalog),
    ]
    print(f"Generated {len(written)} pointer files under {PLUGIN_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
