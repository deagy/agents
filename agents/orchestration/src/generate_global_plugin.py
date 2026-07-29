#!/usr/bin/env python3
"""Regenerate the self-contained Cadre plugin.

The generated package carries full skill content, embedded role instructions,
the tracked runtime suite, and a package-relative Agentic SDLC provider catalog.
It does not depend on this source checkout after installation.

Agent-role wrappers are NOT symmetric, because the two runners differ here:
- Claude Code supports plugin-bundled subagents, auto-discovered from the
  plugin's default agents/ directory (do NOT also declare an "agents" field in
  plugin.json for this — that field expects individual file paths, not a
  directory, and a bare directory string fails manifest validation), so the
  role wrappers go under plugins/cadre/agents/*.md and become
  global automatically when the plugin is installed at user scope.
- Codex CLI has no such mechanism — custom agents are only discovered from
  .codex/agents/ (project) or ~/.codex/agents/ (global) on disk, never from a
  plugin manifest. The *.toml wrappers are generated to the repo-tracked
  staging directory plugins/cadre/codex-agents/ instead. The
  separate `cadre bootstrap-codex` command safely installs their namespaced
  IDs under ~/.codex/agents/ without overwriting bare roles or unowned files;
  this generator itself never writes outside the repository.

A generated bin/cadre wrapper is included too: Claude Code auto-discovers a
plugin's bin/ directory onto the Bash tool's PATH for the duration of a session
(convention-based, no plugin.json field required), so an orchestrating Claude
Code agent gets `cadre <subcommand>` for free once this plugin is installed,
without the human's own shell PATH being touched (that part stays manual — see
README.md "System-wide install"; no plugin can modify a user's shell profile).
Codex CLI has no equivalent bin/ auto-discovery, so this is a Claude-Code-only
convenience layered on top of the manual PATH setup, not a replacement for it.

A generated package-relative agent-catalog.json is loaded by the standalone
kernel through provider.json.

Regenerate after adding/removing a role in agents/catalog.yaml or a skill under
.agents/skills/:

    cadre generate-plugin

Validate deterministically without changing the working tree:

    cadre generate-plugin --check

Use ``--output <directory>`` to render or check an isolated package, which is
useful for tests and packaging review.

(bin/cadre at the repository root; or `python3 agents/orchestration/src/generate_global_plugin.py`
directly if bin/cadre isn't set up yet).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from role_metadata import frontmatter_closing_delimiter_end, is_migrated, strip_frontmatter  # noqa: E402
from routing import parse_catalog_entries  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AGENTS_ROOT = REPOSITORY_ROOT / "agents"
SKILLS_ROOT = REPOSITORY_ROOT / ".agents" / "skills"
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "cadre"
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
SHARED_OVERRIDE_NOTE = (
    "The shared policy content above is this package's global defaults, "
    "embedded at packaging time. The project you are dispatched into may "
    "extend or override them under its own `.agents/shared/`; run `cadre "
    "resolve-shared <filename>` from that project's directory for each "
    "shared file's effective content instead of trusting the embedded text "
    "alone (see agents/shared/README.md in the source suite)."
)

RUNNER_CAPABILITIES_PATH = REPOSITORY_ROOT / "agents" / "runner-capabilities.json"


class ManifestError(ValueError):
    """Raised when `agents/runner-capabilities.json` is missing or does not
    carry the required structure. Fails closed rather than silently falling
    back to a stale hardcoded copy -- see idea #8
    (REQ-CADRE-BACKLOG-8, CM-NFR-5): `CAPABILITY_PROFILES`/`ALLOWED_MODELS`/
    `ALLOWED_CODEX_MODELS`/`ALLOWED_REASONING_EFFORTS` below are derived
    directly from this file at import time (stdlib `json` only, no new
    dependency -- see CM-NFR-4), so there is no separate committed copy that
    could independently drift from it. `agents/runner-capabilities.schema.json`
    additionally validates this file's own shape via a jsonschema-guarded
    standalone check (see `agents/orchestration/test/test_runner_capabilities.py`),
    matching `agents/catalog.schema.json`'s idea #10 precedent, but that
    schema is a supplementary shape check, not the mechanism the fields below
    rely on to stay in sync.
    """


def _load_runner_capabilities(path: Path = RUNNER_CAPABILITIES_PATH) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ManifestError(f"{path}: runner capability manifest not found") from error
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as error:
        raise ManifestError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(manifest, dict):
        raise ManifestError(f"{path}: top-level content must be a JSON object")
    for key in ("capability_tiers", "model_tiers", "allowed_reasoning_efforts"):
        if key not in manifest:
            raise ManifestError(f"{path}: missing required top-level key {key!r}")
    return manifest


def _capability_profiles_from_manifest(manifest: dict[str, Any], path: Path) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for tier, data in manifest["capability_tiers"].items():
        if not isinstance(data, dict) or "tools" not in data or "sandbox_mode" not in data:
            raise ManifestError(f"{path}: capability_tiers[{tier!r}] must declare 'tools' and 'sandbox_mode'")
        profiles[tier] = {"tools": list(data["tools"]), "sandbox_mode": data["sandbox_mode"]}
    return profiles


def _model_tiers_from_manifest(manifest: dict[str, Any], path: Path) -> dict[str, dict[str, str]]:
    tiers: dict[str, dict[str, str]] = {}
    for tier, data in manifest["model_tiers"].items():
        if not isinstance(data, dict) or "codex_model" not in data or "reasoning_effort" not in data:
            raise ManifestError(f"{path}: model_tiers[{tier!r}] must declare 'codex_model' and 'reasoning_effort'")
        tiers[tier] = {"codex_model": data["codex_model"], "reasoning_effort": data["reasoning_effort"]}
    return tiers


_RUNNER_CAPABILITIES = _load_runner_capabilities()

# Single source of truth: `agents/runner-capabilities.json` (idea #8,
# REQ-CADRE-BACKLOG-8). Every constant below is derived from that file at
# import time, not hand-duplicated -- editing the manifest and re-running is
# the only edit location (CM-FR-2), and drift between this module and the
# manifest is structurally impossible (CM-NFR-5) because there is no second
# copy to fall out of sync.
CAPABILITY_PROFILES: dict[str, dict[str, Any]] = _capability_profiles_from_manifest(
    _RUNNER_CAPABILITIES, RUNNER_CAPABILITIES_PATH
)
MODEL_TIERS: dict[str, dict[str, str]] = _model_tiers_from_manifest(_RUNNER_CAPABILITIES, RUNNER_CAPABILITIES_PATH)
ALLOWED_MODELS = set(MODEL_TIERS)
ALLOWED_CODEX_MODELS = {data["codex_model"] for data in MODEL_TIERS.values()}
# Shared between both wrappers (Claude Code's `effort:` frontmatter and
# Codex's `model_reasoning_effort` TOML key) -- restricted to the subset
# both runners accept, so a single catalog.yaml value is always valid on
# either side. See catalog.yaml's `reasoning_effort` comment for the source
# of this list.
ALLOWED_REASONING_EFFORTS = set(_RUNNER_CAPABILITIES["allowed_reasoning_efforts"])

GENERATED_MARKER = "<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->"
GENERATED_TOP_LEVEL = {"skills", "agents", "codex-agents", "suite", "agent-catalog.json", "bin"}


def load_catalog(path: Path) -> dict[str, dict[str, Any]]:
    agents: dict[str, dict[str, Any]] = parse_catalog_entries(path.read_text(encoding="utf-8"))
    if not agents:
        raise ValueError("No agents found in catalog.yaml")
    for agent_id, metadata in agents.items():
        capability = metadata.get("capability")
        if capability not in CAPABILITY_PROFILES:
            raise ValueError(
                f"Agent {agent_id} must declare one of: {', '.join(sorted(CAPABILITY_PROFILES))}"
            )
        model = metadata.get("model")
        if model is not None and model not in ALLOWED_MODELS:
            raise ValueError(
                f"Agent {agent_id} declares an unsupported model tier {model!r}; "
                f"must be one of: {', '.join(sorted(ALLOWED_MODELS))}"
            )
        codex_model = metadata.get("codex_model")
        if codex_model is not None and codex_model not in ALLOWED_CODEX_MODELS:
            raise ValueError(
                f"Agent {agent_id} declares an unsupported codex_model {codex_model!r}; "
                f"must be one of: {', '.join(sorted(ALLOWED_CODEX_MODELS))}"
            )
        reasoning_effort = metadata.get("reasoning_effort")
        if reasoning_effort is not None and reasoning_effort not in ALLOWED_REASONING_EFFORTS:
            raise ValueError(
                f"Agent {agent_id} declares an unsupported reasoning_effort {reasoning_effort!r}; "
                f"must be one of: {', '.join(sorted(ALLOWED_REASONING_EFFORTS))}"
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
    for path in (plugin_root / "agent-catalog.json", plugin_root / "bin" / "cadre"):
        if path.exists():
            path.unlink()


def generate_skill_copies(plugin_root: Path) -> list[Path]:
    written = []
    tracked = {
        relative
        for relative in subprocess.run(
            ["git", "ls-files", ".agents/skills"], cwd=REPOSITORY_ROOT,
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout.splitlines()
        if (REPOSITORY_ROOT / relative).is_file()
    }
    for skill_dir in sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        target_dir = plugin_root / "skills" / skill_dir.name
        for relative_text in sorted(path for path in tracked if path.startswith(f".agents/skills/{skill_dir.name}/")):
            source = REPOSITORY_ROOT / relative_text
            if source.is_symlink():
                raise ValueError(f"Symlinks are not allowed in packaged skills: {relative_text}")
            target = target_dir / Path(relative_text).relative_to(skill_dir.relative_to(REPOSITORY_ROOT))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
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
        model = metadata.get("model")
        codex_model = metadata.get("codex_model")
        reasoning_effort = metadata.get("reasoning_effort")
        profile = CAPABILITY_PROFILES[capability]
        definition_path = AGENTS_ROOT / definition
        shared_content = "\n\n".join(
            f"# Shared policy: {relative}\n\n{(REPOSITORY_ROOT / relative).read_text(encoding='utf-8').strip()}"
            for relative in SHARED_POLICIES
        )
        description = f"Secure cloud agent suite role for the {phase} phase ({agent_id})."
        # A migrated role's AGENT.md carries `---`-delimited frontmatter
        # ahead of its prose body (see role_metadata.py); that frontmatter
        # is generated-file bookkeeping for catalog.yaml/routing.yaml, not
        # role instructions, so it must never be embedded into the wrapper.
        # A no-op today (no AGENT.md has frontmatter yet).
        role_body = strip_frontmatter(definition_path.read_text(encoding="utf-8")).strip()
        instructions = (
            f"# Role: {agent_id}\n\n{role_body}"
            f"\n\n{shared_content}\n\n{SHARED_OVERRIDE_NOTE}\n\n{ASK_HUMAN_RULE}"
        )

        md_target = plugin_root / "agents" / f"{agent_id}.md"
        md_lines = [
            "---",
            f"name: {agent_id}",
            f"description: {description}",
            f"tools: {', '.join(profile['tools'])}",
        ]
        if model:
            md_lines.append(f"model: {model}")
        if reasoning_effort:
            md_lines.append(f"effort: {reasoning_effort}")
        md_lines += [
            "generated: true",
            f"canonical_source: agents/{definition}",
            "---",
            "",
            instructions,
            "",
        ]
        write(md_target, "\n".join(md_lines))
        written.append(md_target)

        # Codex has no plugin-bundled-agent mechanism; this is a repo-tracked
        # staging copy, not something Codex discovers directly (see module docstring).
        # `model` uses catalog.yaml's separate `codex_model` OpenAI identifier, not
        # the Claude Code wrapper's haiku/sonnet/opus tier name above — the two
        # runners don't share a model-naming space. Re-verify these identifiers
        # against current Codex CLI docs before relying on them in automation.
        codex_agent_id = f"agents-{agent_id}"
        toml_target = plugin_root / "codex-agents" / f"{codex_agent_id}.toml"
        toml_lines = [
            f"# GENERATED FILE: canonical source is agents/{definition}",
            f"name = {toml_string(codex_agent_id)}",
            f"description = {toml_string(description)}",
            f"sandbox_mode = {toml_string(profile['sandbox_mode'])}",
        ]
        if codex_model:
            toml_lines.append(f"model = {toml_string(codex_model)}")
        if reasoning_effort:
            toml_lines.append(f"model_reasoning_effort = {toml_string(reasoning_effort)}")
        toml_lines += [
            f"developer_instructions = {toml_string(instructions)}",
            "",
        ]
        toml_body = "\n".join(toml_lines)
        write(toml_target, toml_body)
        written.append(toml_target)
    return written


def derive_kind(definition: str) -> str:
    if definition.startswith("review/") or definition == "engineering/test-engineer/AGENT.md":
        return "reviewer"
    if definition.startswith("support/"):
        return "specialist"
    if definition in {"documentation/evidence-curator/AGENT.md", "knowledge-store/AGENT.md"}:
        return "specialist"
    return "author"


def generate_agent_catalog_export(catalog: dict[str, dict[str, Any]], plugin_root: Path) -> Path:
    """Package-relative catalog export consumed through provider.json."""
    agents = {
        agent_id: {
            "phase": metadata.get("phase", "unknown"),
            "kind": derive_kind(metadata["definition"]),
            "capabilities": (
                ["reviewer"]
                if derive_kind(metadata["definition"]) == "reviewer"
                else ["author", "dispatch"]
            ),
            "definition": f"suite/agents/{metadata['definition']}",
        }
        for agent_id, metadata in sorted(catalog.items())
    }
    target = plugin_root / "agent-catalog.json"
    write(target, json.dumps({"schema_version": 1, "agents": agents}, indent=2) + "\n")
    return target


# Subcommands from bin/subcommands.tsv that manage this source repository
# itself (regenerating/inspecting the packaged plugin) and therefore have no
# meaning once shipped inside the plugin they regenerate.
PACKAGED_SUBCOMMAND_EXCLUSIONS = {"generate-plugin", "generate-authority-aides", "generate-role-metadata", "version"}

# Extra argv this packaged wrapper must inject ahead of the caller's own
# "$@" for a subcommand whose packaged invocation needs plugin-relative
# context bin/subcommands.tsv has no column for (bootstrap-codex's wrapper
# source lives under the packaged plugin, not this source repository).
PACKAGED_SUBCOMMAND_EXTRA_ARGS = {
    "bootstrap-codex": '--source "$PLUGIN_ROOT/codex-agents"',
}


def load_subcommand_table(repository_root: Path) -> list[tuple[str, str, str]]:
    table = repository_root / "bin" / "subcommands.tsv"
    rows = []
    for line in table.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        name, script, description = line.split("\t")
        rows.append((name, script, description))
    return rows


def packaged_subcommands(repository_root: Path) -> list[tuple[str, str]]:
    """The single derivation point for which bin/subcommands.tsv entries
    ship in the packaged plugin's own `bin/cadre` and which script path each
    maps to, so a script rename or new subcommand only needs to change
    bin/subcommands.tsv -- not this generator's shell text too."""
    return [
        (name, script)
        for name, script, _description in load_subcommand_table(repository_root)
        if name not in PACKAGED_SUBCOMMAND_EXCLUSIONS
    ]


def generate_bin_wrapper(plugin_root: Path) -> Path:
    target = plugin_root / "bin" / "cadre"
    rows = packaged_subcommands(REPOSITORY_ROOT)
    case_lines = [
        '  {name}) exec "$AGENT_PYTHON" "$SUITE_ROOT/{script}" {extra}"$@" ;;'.format(
            name=name,
            script=script,
            extra=(PACKAGED_SUBCOMMAND_EXTRA_ARGS[name] + " ") if name in PACKAGED_SUBCOMMAND_EXTRA_ARGS else "",
        )
        for name, script in rows
    ]
    usage = "|".join([*(name for name, _script in rows), "sdlc"])
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
            '  [ -n "$sdlc_bin" ] || { echo "cadre: install Agentic SDLC v0.3.x from https://github.com/deagy/agentic-sdlc" >&2; exit 1; }',
            '  exec "$sdlc_bin" --provider "$PLUGIN_ROOT/provider.json" "$@"',
            "fi",
            "AGENT_PYTHON=",
            "for candidate in python3 python; do",
            '  command -v "$candidate" >/dev/null 2>&1 || continue',
            '  if "$candidate" -c \'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)\' 2>/dev/null; then AGENT_PYTHON="$candidate"; break; fi',
            "done",
            '[ -n "$AGENT_PYTHON" ] || { echo "cadre: Python 3.10+ is required" >&2; exit 1; }',
            'case "$command_name" in',
            *case_lines,
            f'  help|-h|--help) echo "Usage: cadre {{{usage}}} [args...]" ;;',
            '  *) echo "cadre: unknown subcommand $command_name" >&2; exit 1 ;;',
            "esac",
            "",
        ]
    )
    write(target, body)
    target.chmod(0o755)
    return target


def generate_suite_copy(catalog: dict[str, dict[str, Any]], plugin_root: Path) -> list[Path]:
    tracked = {
        relative
        for relative in subprocess.run(
        ["git", "ls-files", "agents"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        ).stdout.splitlines()
        if (REPOSITORY_ROOT / relative).is_file()
    }
    contract_helper = "agents/orchestration/src/agentic_sdlc_contracts.py"
    if (REPOSITORY_ROOT / contract_helper).is_file():
        tracked.add(contract_helper)
    bootstrap_helper = "agents/orchestration/src/sync_codex_agents.py"
    if (REPOSITORY_ROOT / bootstrap_helper).is_file():
        tracked.add(bootstrap_helper)
    role_paths = {f"agents/{metadata['definition']}" for metadata in catalog.values()}
    # `catalog` was parsed straight off the worktree copy of catalog.yaml, but
    # `tracked` only reflects git's index -- an uncommitted new role's
    # AGENT.md would otherwise pass this function silently, then still get a
    # wrapper and an agent-catalog.json entry from generate_agent_wrappers()/
    # generate_agent_catalog_export() (which read `catalog` directly, not
    # `tracked`), producing a package that references a suite file that was
    # never copied. Fail loudly here instead.
    untracked_role_paths = role_paths - tracked
    if untracked_role_paths:
        raise ValueError(
            "agents/catalog.yaml references role definition file(s) not tracked in git; "
            "commit them (git add) before regenerating the plugin: "
            + ", ".join(sorted(untracked_role_paths))
        )
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
        elif relative in role_paths or relative in {
            "agents/catalog.yaml",
            "agents/catalog.schema.json",
            "agents/catalog-order.txt",
            "agents/_catalog_header.yaml.tmpl",
            "agents/runner-capabilities.json",
            "agents/runner-capabilities.schema.json",
            "agents/authority/aides.yaml",
            "agents/authority/_template.md.tmpl",
            "agents/README.md",
            "agents/RUNBOOK.md",
        }:
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
            and not relative.endswith("plugin_version.py")
            # These two scripts import generate_global_plugin.py (excluded
            # above) and their subcommands are already excluded from the
            # packaged bin/cadre wrapper via PACKAGED_SUBCOMMAND_EXCLUSIONS
            # -- packaging them anyway would ship a non-functional entry
            # point (ModuleNotFoundError on generate_global_plugin) that
            # looks runnable but isn't.
            and not relative.endswith("generate_role_metadata.py")
            and not relative.endswith("generate_authority_aides.py")
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
            content = content.replace("../bin/cadre", "../../bin/cadre")
            content = content.replace("../README.md", "README.md")
            content = content.replace("`../README.md`", "`README.md`")
            content = content.replace("../plugins/cadre/README.md", "../README.md")
            content = content.replace("../plugins/cadre/", "./")
            # A migrated role's AGENT.md starts with `---`-delimited
            # frontmatter (see role_metadata.py); inserting the marker at
            # byte 0 would land it inside that frontmatter block instead of
            # before it, corrupting the block. Insert after the closing
            # delimiter instead, mirroring generate_skill_copies()'s
            # SKILL.md package-note placement above. No-op today (no
            # AGENT.md has frontmatter yet), but no source file in the
            # copied suite happens to start with "---" today either, so
            # this only ever takes the plain byte-0 path currently. Use
            # role_metadata's exact-line delimiter detection rather than a
            # raw substring search: a raw search would false-match a
            # literal "---" embedded inside a frontmatter value's text
            # before the real closing delimiter line.
            if is_migrated(content):
                frontmatter_end = frontmatter_closing_delimiter_end(content)
                content = content[:frontmatter_end] + f"\n\n{GENERATED_MARKER}" + content[frontmatter_end:]
            else:
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
            if path.is_file()
            and path.relative_to(root).parts[0] in GENERATED_TOP_LEVEL
            and "__pycache__" not in path.relative_to(root).parts
            and path.suffix not in (".pyc", ".pyo")
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
    if "--check" not in arguments and output_root.exists() and output_root != PLUGIN_ROOT:
        marker = output_root / ".codex-plugin" / "plugin.json"
        if any(output_root.iterdir()) and not marker.is_file():
            raise SystemExit("--output must be a new directory or an existing generated plugin")
    if "--check" in arguments:
        with tempfile.TemporaryDirectory(prefix="cadre-plugin-") as temporary_directory:
            candidate = Path(temporary_directory) / "cadre"
            generate_package(catalog, candidate)
            if not output_root.exists() or not files_equal(candidate, output_root):
                print("Generated plugin is stale or non-deterministic; run cadre generate-plugin", file=sys.stderr)
                return 1
        kernel = os.environ.get("AGENTIC_SDLC_BIN") or shutil.which("agentic-sdlc")
        if kernel:
            checked = subprocess.run(
                [kernel, "--provider", str(PLUGIN_ROOT / "provider.json"), "provider", "list"],
                cwd=REPOSITORY_ROOT, check=False, capture_output=True, text=True, encoding="utf-8",
            )
            if checked.returncode != 0:
                print(f"Provider validation failed: {checked.stderr.strip() or checked.stdout.strip()}", file=sys.stderr)
                return 1
        print(f"Generated plugin is current under {output_root}")
        return 0
    written = generate_package(catalog, output_root)
    print(f"Generated {len(written)} self-contained files under {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
