#!/usr/bin/env python3
"""Regenerate the self-contained Secure Cloud Agents plugin.

The generated package carries full skill content, embedded role instructions,
the tracked runtime suite, and a package-relative Agentic SDLC provider catalog.
It does not depend on this source checkout after installation.

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

A generated package-relative agent-catalog.json is loaded by the standalone
kernel through provider.json.

Regenerate after adding/removing a role in agents/catalog.yaml or a skill under
.agents/skills/:

    agents generate-plugin

Validate deterministically without changing the working tree:

    agents generate-plugin --check

Use ``--output <directory>`` to render or check an isolated package, which is
useful for tests and packaging review.

(bin/agents at the repository root; or `python3 agents/orchestration/src/generate_global_plugin.py`
directly if bin/agents isn't set up yet).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
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
ASK_HUMAN_RULE = (
    "You are a dispatched subagent: you cannot ask the human directly. If you "
    "reach a decision only a human can make, stop and return a clearly labeled "
    "blocking question in your result instead of guessing or proceeding."
)

CAPABILITY_PROFILES: dict[str, dict[str, Any]] = {
    "read_only": {
        "tools": ["Read", "Grep", "Glob"],
        "sandbox_mode": "read-only",
    },
    "document_author": {
        "tools": ["Read", "Grep", "Glob", "Bash", "Edit", "Write"],
        "sandbox_mode": "workspace-write",
    },
    "code_author": {
        "tools": ["Read", "Grep", "Glob", "Bash", "Edit", "Write"],
        "sandbox_mode": "workspace-write",
    },
    "test_author": {
        "tools": ["Read", "Grep", "Glob", "Bash", "Edit", "Write"],
        "sandbox_mode": "workspace-write",
    },
    "environment_operator": {
        "tools": ["Read", "Grep", "Glob", "Bash", "Edit", "Write"],
        "sandbox_mode": "workspace-write",
    },
}

GENERATED_MARKER = "<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->"
GENERATED_TOP_LEVEL = {"skills", "agents", "codex-agents", "suite", "agent-catalog.json", "bin"}


def load_catalog(path: Path) -> dict[str, dict[str, Any]]:
    agents: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^  ([a-z0-9-]+):\s*$", line)
        if match:
            current = match.group(1)
            agents[current] = {}
            continue
        if current and line.strip().startswith(("definition:", "phase:", "capability:")):
            key, value = line.strip().split(":", 1)
            agents[current][key] = value.strip()
    if not agents:
        raise ValueError("No agents found in catalog.yaml")
    for agent_id, metadata in agents.items():
        capability = metadata.get("capability")
        if capability not in CAPABILITY_PROFILES:
            raise ValueError(
                f"Agent {agent_id} must declare one of: {', '.join(sorted(CAPABILITY_PROFILES))}"
            )
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


def reset_generated_content(plugin_root: Path) -> None:
    for name in ("skills", "agents", "codex-agents", "suite"):
        path = plugin_root / name
        if path.exists():
            shutil.rmtree(path)
    for path in (plugin_root / "agent-catalog.json", plugin_root / "bin" / "agents"):
        if path.exists():
            path.unlink()


def generate_skill_copies(plugin_root: Path) -> list[Path]:
    written = []
    for skill_dir in sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        target_dir = plugin_root / "skills" / skill_dir.name
        shutil.copytree(skill_dir, target_dir)
        target = target_dir / "SKILL.md"
        content = target.read_text(encoding="utf-8")
        frontmatter_end = content.find("---", 3) + 3
        package_note = (
            "\n\n> Packaged suite note: when the current project has no local `agents/` "
            "tree, resolve suite files under `../../suite/agents/` relative to this "
            "`SKILL.md`. The packaged plugin is self-contained; do not look for the "
            "source checkout.\n"
        )
        target.write_text(content[:frontmatter_end] + package_note + content[frontmatter_end:], encoding="utf-8")
        written.extend(path for path in target_dir.rglob("*") if path.is_file())
    return written


def generate_agent_wrappers(catalog: dict[str, dict[str, Any]], plugin_root: Path) -> list[Path]:
    written = []
    for agent_id, metadata in sorted(catalog.items()):
        definition = metadata["definition"]
        phase = metadata.get("phase", "unknown")
        capability = metadata["capability"]
        profile = CAPABILITY_PROFILES[capability]
        definition_path = AGENTS_ROOT / definition
        shared_content = "\n\n".join(
            f"# Shared policy: {relative}\n\n{(REPOSITORY_ROOT / relative).read_text(encoding='utf-8').strip()}"
            for relative in SHARED_POLICIES
        )
        description = f"Secure cloud agent suite role for the {phase} phase ({agent_id})."
        instructions = (
            f"# Role: {agent_id}\n\n{definition_path.read_text(encoding='utf-8').strip()}"
            f"\n\n{shared_content}\n\n{ASK_HUMAN_RULE}"
        )

        md_target = plugin_root / "agents" / f"{agent_id}.md"
        md_body = "\n".join(
            [
                "---",
                f"name: {agent_id}",
                f"description: {description}",
                f"tools: {', '.join(profile['tools'])}",
                "generated: true",
                f"canonical_source: agents/{definition}",
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
        toml_target = plugin_root / "codex-agents" / f"{agent_id}.toml"
        toml_body = "\n".join(
            [
                f"# GENERATED FILE: canonical source is agents/{definition}",
                f"name = {toml_string(agent_id)}",
                f"description = {toml_string(description)}",
                f"sandbox_mode = {toml_string(profile['sandbox_mode'])}",
                f"developer_instructions = {toml_string(instructions)}",
                "",
            ]
        )
        write(toml_target, toml_body)
        written.append(toml_target)
    return written


def derive_kind(definition: str) -> str:
    if definition.startswith("review/") or definition == "engineering/test-engineer/AGENT.md":
        return "reviewer"
    if definition.startswith("support/"):
        return "support"
    if definition in {"documentation/evidence-curator/AGENT.md", "knowledge-store/AGENT.md"}:
        return "curator"
    return "author"


def generate_agent_catalog_export(catalog: dict[str, dict[str, Any]], plugin_root: Path) -> Path:
    """Package-relative catalog export consumed through provider.json."""
    agents = {
        agent_id: {
            "phase": metadata.get("phase", "unknown"),
            "kind": derive_kind(metadata["definition"]),
            "capability": metadata["capability"],
            "definition": f"suite/agents/{metadata['definition']}",
        }
        for agent_id, metadata in sorted(catalog.items())
    }
    target = plugin_root / "agent-catalog.json"
    write(target, json.dumps({"generated": True, "canonical_source": "agents/catalog.yaml", "agents": agents}, indent=2) + "\n")
    return target


def generate_bin_wrapper(plugin_root: Path) -> Path:
    target = plugin_root / "bin" / "agents"
    body = "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            'BIN_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)',
            'PLUGIN_ROOT=$(CDPATH= cd -- "$BIN_DIR/.." && pwd)',
            'SUITE_ROOT="$PLUGIN_ROOT/suite"',
            'command_name="${1:-help}"',
            '[ "$#" -gt 0 ] && shift || true',
            'if [ "$command_name" = "sdlc" ]; then',
            '  sdlc_bin="${AGENTIC_SDLC_BIN:-}"',
            '  if [ -z "$sdlc_bin" ]; then sdlc_bin=$(command -v agentic-sdlc || true); fi',
            '  [ -n "$sdlc_bin" ] || { echo "agents: install Agentic SDLC v0.2.x from https://github.com/deagy/agentic-sdlc" >&2; exit 1; }',
            '  exec "$sdlc_bin" --provider "$PLUGIN_ROOT/provider.json" "$@"',
            "fi",
            "AGENT_PYTHON=",
            "for candidate in python3 python; do",
            '  command -v "$candidate" >/dev/null 2>&1 || continue',
            '  if "$candidate" -c \'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)\' 2>/dev/null; then AGENT_PYTHON="$candidate"; break; fi',
            "done",
            '[ -n "$AGENT_PYTHON" ] || { echo "agents: Python 3.10+ is required" >&2; exit 1; }',
            'case "$command_name" in',
            '  select) exec "$AGENT_PYTHON" "$SUITE_ROOT/agents/orchestration/src/select_agents.py" "$@" ;;',
            '  knowledge) exec "$AGENT_PYTHON" "$SUITE_ROOT/agents/knowledge-store/src/cli.py" "$@" ;;',
            '  validate-run) exec "$AGENT_PYTHON" "$SUITE_ROOT/agents/orchestration/src/validate_run_record.py" "$@" ;;',
            '  help|-h|--help) echo "Usage: agents {select|knowledge|sdlc|validate-run} [args...]" ;;',
            '  *) echo "agents: unknown subcommand $command_name" >&2; exit 1 ;;',
            "esac",
            "",
        ]
    )
    write(target, body)
    target.chmod(0o755)
    return target


def generate_suite_copy(catalog: dict[str, dict[str, Any]], plugin_root: Path) -> list[Path]:
    tracked = set(subprocess.run(
        ["git", "ls-files", "agents"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines())
    contract_helper = "agents/orchestration/src/agentic_sdlc_contracts.py"
    if (REPOSITORY_ROOT / contract_helper).is_file():
        tracked.add(contract_helper)
    role_paths = {f"agents/{metadata['definition']}" for metadata in catalog.values()}
    documentation_paths = {
        "AGENTS.md",
        "CONTRIBUTING.md",
        "IDENTITY.md",
        *(
            str(path.relative_to(REPOSITORY_ROOT))
            for path in (REPOSITORY_ROOT / "docs").rglob("*")
            if path.is_file()
        ),
    }
    selected: list[str] = []
    for relative in sorted(tracked):
        if relative in documentation_paths:
            selected.append(relative)
        elif relative in role_paths or relative in {"agents/catalog.yaml", "agents/README.md", "agents/RUNBOOK.md"}:
            selected.append(relative)
        elif relative.startswith(("agents/shared/", "agents/workflows/")):
            selected.append(relative)
        elif (
            relative.startswith("agents/orchestration/")
            and "/runs/" not in relative
            and "/test/" not in relative
            and "/examples/" not in relative
            and not relative.endswith("generate_global_plugin.py")
            and not relative.endswith("migrate_execution_summary.py")
        ):
            selected.append(relative)
        elif relative.startswith("agents/knowledge-store/src/") or relative in {
            "agents/knowledge-store/README.md",
            "agents/knowledge-store/SECURITY.md",
        }:
            selected.append(relative)
    selected.extend(
        relative
        for relative in sorted(documentation_paths)
        if relative not in selected and (REPOSITORY_ROOT / relative).is_file()
    )
    written: list[Path] = []
    package_readme_source = PLUGIN_ROOT / "README.md"
    package_readme_target = plugin_root / "suite" / "README.md"
    package_readme_content = package_readme_source.read_text(encoding="utf-8")
    package_readme_content = f"{GENERATED_MARKER}\n\n{package_readme_content}"
    write(package_readme_target, package_readme_content)
    written.append(package_readme_target)
    for relative in selected:
        source = REPOSITORY_ROOT / relative
        target = plugin_root / "suite" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() == ".md":
            content = source.read_text(encoding="utf-8")
            content = content.replace("../bin/agents", "../../bin/agents")
            content = content.replace("../README.md", "README.md")
            content = content.replace("`../README.md`", "`README.md`")
            content = content.replace("../plugins/secure-cloud-agents/README.md", "../README.md")
            content = content.replace("../plugins/secure-cloud-agents/", "./")
            content = f"{GENERATED_MARKER}\n\n{content}"
            write(target, content)
        else:
            shutil.copy2(source, target)
        written.append(target)
    return written


def generate_package(catalog: dict[str, dict[str, Any]], plugin_root: Path) -> list[Path]:
    reset_generated_content(plugin_root)
    return generate_skill_copies(plugin_root) + generate_suite_copy(catalog, plugin_root) + generate_agent_wrappers(catalog, plugin_root) + [
        generate_bin_wrapper(plugin_root),
        generate_agent_catalog_export(catalog, plugin_root),
    ]


def files_equal(left: Path, right: Path) -> bool:
    def generated_files(root: Path) -> set[Path]:
        return {
            path.relative_to(root)
            for path in root.rglob("*")
            if path.is_file() and path.relative_to(root).parts[0] in GENERATED_TOP_LEVEL
        }

    left_files = generated_files(left)
    right_files = generated_files(right)
    if left_files != right_files:
        return False
    return all((left / relative).read_bytes() == (right / relative).read_bytes() for relative in left_files)


def main() -> int:
    catalog = load_catalog(AGENTS_ROOT / "catalog.yaml")
    arguments = sys.argv[1:]
    output_root = PLUGIN_ROOT
    if "--output" in arguments:
        output_index = arguments.index("--output")
        try:
            output_root = Path(arguments[output_index + 1]).resolve()
        except IndexError as error:
            raise SystemExit("--output requires a directory") from error
    if "--check" in arguments:
        with tempfile.TemporaryDirectory(prefix="secure-cloud-agents-plugin-") as temporary_directory:
            candidate = Path(temporary_directory) / "secure-cloud-agents"
            generate_package(catalog, candidate)
            if not output_root.exists() or not files_equal(candidate, output_root):
                print("Generated plugin is stale or non-deterministic; run agents generate-plugin", file=sys.stderr)
                return 1
        print(f"Generated plugin is current under {output_root}")
        return 0
    written = generate_package(catalog, output_root)
    print(f"Generated {len(written)} self-contained files under {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
