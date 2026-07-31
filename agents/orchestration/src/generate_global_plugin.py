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
  role wrappers go under the package's agents/*.md and become
  global automatically when the plugin is installed at user scope.
- Codex CLI has no such mechanism — custom agents are only discovered from
  .codex/agents/ (project) or ~/.codex/agents/ (global) on disk, never from a
  plugin manifest. The *.toml wrappers are generated to this repository's
  tracked staging directory provider/codex-agents/ instead (by `cadre
  generate-role-metadata`), and copied into the package from there. The
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

The package itself is maintained in a separate repository, deagy/cadre-plugin,
which is almost entirely this script's output: only the two plugin manifests
carrying the release version are hand-authored there (see PACKAGE_ASSETS).
``--output <directory>`` points at a checkout of that repository and is
therefore required — this source repository has no plugins/ directory of its
own to write into.

Regenerate after adding/removing a role in agents/catalog.yaml or a skill under
.agents/skills/:

    cadre generate-plugin --output /path/to/cadre-plugin

Validate deterministically without changing the working tree:

    cadre generate-plugin --check --output /path/to/cadre-plugin

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
# This repository's Agentic SDLC provider bundle. Register-owned, tracked here,
# and copied verbatim into the package by generate_provider_copy(): the
# pip/pipx distribution vendors this directory (see pyproject.toml) so `cadre
# sdlc` and `cadre bootstrap-codex` keep working from an install without a
# plugin checkout. provider.json/profiles/extensions are hand-authored;
# agent-catalog.json and codex-agents/ are generated from agents/catalog.yaml
# by `cadre generate-role-metadata`, which also drift-checks them.
PROVIDER_ROOT = REPOSITORY_ROOT / "provider"
# The packaged plugin's own README. Register-owned like the provider bundle:
# the generator renders it to both <package>/README.md and
# <package>/suite/README.md, so the package has no hand-authored input this
# script must read back out of the plugin repository -- `--output` can point
# at an empty directory and still produce a complete package.
PACKAGING_README = REPOSITORY_ROOT / "packaging" / "plugin-README.md"
PROVIDER_BUNDLE = ("provider.json", "agent-catalog.json", "profiles", "extensions", "codex-agents")
# Register-only member of provider/: verbatim copies of every role's AGENT.md.
# The kernel resolves agent-catalog.json's `definition` values relative to the
# directory holding that file and rejects anything escaping it
# (agentic_sdlc.load_agent_catalog), so role content reachable from
# provider/agent-catalog.json has to live *under* provider/ -- a relative path
# back out to agents/ would raise. Without it, `cadre sdlc init --profile
# secure-cloud` silently falls back to one-line generic role instructions
# (rich_agent_content() returns None for a missing file), which is what the pip
# distribution has always done and what a register checkout would otherwise
# start doing after the plugin split.
#
# NOT copied into the package: the package reaches the same content through
# suite/agents/, and a package-root roles/ would be dead weight. Hence
# PROVIDER_DEFINITION_PREFIX below.
PROVIDER_ROLES_DIRNAME = "roles"
# agent-catalog.json's `definition` values are relative to whichever copy of
# the file is being read, and the two copies sit in differently shaped trees:
# provider/roles/... in the register, suite/agents/... in the package. The
# register spelling is authoritative and generate_provider_copy() rewrites it
# for the package.
PROVIDER_DEFINITION_PREFIX = f"{PROVIDER_ROLES_DIRNAME}/"
PACKAGE_DEFINITION_PREFIX = "suite/agents/"
# The only files in the plugin package this script does NOT produce. Both
# carry the package's release version, which is deliberately hand-set in the
# plugin repository (see its tools/plugin_version.py) so a release stays a
# separate, reviewed act from a content regeneration. GENERATED_TOP_LEVEL
# below is the complement: everything reset_generated_content() removes and
# files_equal() compares.
PACKAGE_ASSETS = (".claude-plugin", ".codex-plugin")
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
GENERATED_TOP_LEVEL = {
    "skills", "agents", "suite", "bin",
    # The provider bundle, copied verbatim from this repository's provider/
    # by generate_provider_copy(). Generated *for the package* even though
    # some members are hand-authored in the register -- inside the package
    # they are output, and drift against the register must fail the check.
    *PROVIDER_BUNDLE,
    "README.md",
}


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
    # Derived from GENERATED_TOP_LEVEL rather than re-listed, so a new member
    # can never be generated-but-not-reset (which would leave stale files that
    # files_equal() then reports as drift forever, with no way to regenerate
    # out of it). bin/ is the one entry not removed wholesale: only bin/cadre
    # is generated, and the directory may legitimately hold nothing else.
    for name in sorted(GENERATED_TOP_LEVEL - {"bin"}):
        path = plugin_root / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    cadre_wrapper = plugin_root / "bin" / "cadre"
    if cadre_wrapper.exists():
        cadre_wrapper.unlink()


def generate_provider_copy(catalog: dict[str, dict[str, Any]], plugin_root: Path) -> list[Path]:
    """Copy this repository's provider/ bundle into the package root.

    The bundle is register-owned (see PROVIDER_ROOT): the package receives a
    verbatim copy so an installed plugin carries its own provider contracts,
    and files_equal() then fails the drift check if the package's copy ever
    diverges from the register's.
    """
    # The generated members of provider/ are produced by
    # `cadre generate-role-metadata`, not here, so this generator can only copy
    # whatever the register last committed. Editing a role's AGENT.md and
    # running `generate-plugin` alone would refresh the package's Claude Code
    # wrappers (built live from the catalog) while silently packaging stale
    # Codex wrappers and a stale catalog export -- and a following --check,
    # which compares package against the same stale register content, would
    # call it current. Fail loudly instead.
    stale = [
        str(PROVIDER_ROOT / relative)
        for relative, expected in {
            "agent-catalog.json": agent_catalog_export_content(catalog),
            **{f"codex-agents/{name}": body for name, body in codex_wrapper_contents(catalog).items()},
        }.items()
        if not (PROVIDER_ROOT / relative).is_file()
        or (PROVIDER_ROOT / relative).read_text(encoding="utf-8") != expected
    ]
    if stale:
        raise SystemExit(
            "provider/ is stale; run `cadre generate-role-metadata` before regenerating the "
            "package: " + ", ".join(sorted(stale)[:5]) + (" ..." if len(stale) > 5 else "")
        )
    written: list[Path] = []
    for name in PROVIDER_BUNDLE:
        source = PROVIDER_ROOT / name
        if not source.exists():
            raise SystemExit(
                f"{source}: missing from the provider bundle. Run "
                "`cadre generate-role-metadata` if it is generated content."
            )
        target = plugin_root / name
        if source.is_dir():
            # symlinks=False would dereference, silently vendoring out-of-tree
            # content into a published package; refuse instead, matching
            # generate_skill_copies()'s stance.
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise SystemExit(f"{path}: symlinks are not packaged; replace it with a regular file")
            shutil.copytree(source, target)
            written.extend(path for path in sorted(target.rglob("*")) if path.is_file())
        elif name == "agent-catalog.json":
            # Re-point `definition` from the register's provider/roles/ tree to
            # the package's own suite/agents/ copy of the same files. The
            # kernel resolves these relative to whichever copy it reads and
            # rejects escapes, so the two trees genuinely need different
            # spellings -- see PROVIDER_DEFINITION_PREFIX.
            catalog = json.loads(source.read_text(encoding="utf-8"))
            for metadata in catalog["agents"].values():
                definition = metadata["definition"]
                if not definition.startswith(PROVIDER_DEFINITION_PREFIX):
                    raise SystemExit(
                        f"{source}: definition {definition!r} does not start with "
                        f"{PROVIDER_DEFINITION_PREFIX!r}; run `cadre generate-role-metadata`"
                    )
                metadata["definition"] = (
                    PACKAGE_DEFINITION_PREFIX + definition[len(PROVIDER_DEFINITION_PREFIX):]
                )
            write(target, json.dumps(catalog, indent=2) + "\n")
            written.append(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            written.append(target)
    return written


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


def role_wrapper_inputs(agent_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """The wrapper content both runners derive from one role.

    Shared by generate_agent_wrappers() (Claude Code, package-only) and
    generate_codex_wrappers() (Codex, register-side under provider/), which
    write to different repositories but must embed byte-identical role and
    shared-policy instructions.
    """
    definition = metadata["definition"]
    phase = metadata.get("phase", "unknown")
    profile = CAPABILITY_PROFILES[metadata["capability"]]
    shared_content = "\n\n".join(
        f"# Shared policy: {relative}\n\n{(REPOSITORY_ROOT / relative).read_text(encoding='utf-8').strip()}"
        for relative in SHARED_POLICIES
    )
    # A migrated role's AGENT.md carries `---`-delimited frontmatter
    # ahead of its prose body (see role_metadata.py); that frontmatter
    # is generated-file bookkeeping for catalog.yaml/routing.yaml, not
    # role instructions, so it must never be embedded into the wrapper.
    role_body = strip_frontmatter((AGENTS_ROOT / definition).read_text(encoding="utf-8")).strip()
    description = f"Secure cloud agent suite role for the {phase} phase ({agent_id})."
    return {
        "definition": definition,
        "description": description,
        "profile": profile,
        "model": metadata.get("model"),
        "codex_model": metadata.get("codex_model"),
        "reasoning_effort": metadata.get("reasoning_effort"),
        "instructions": (
            f"# Role: {agent_id}\n\n{role_body}"
            f"\n\n{shared_content}\n\n{SHARED_OVERRIDE_NOTE}\n\n{ASK_HUMAN_RULE}"
        ),
    }


def generate_agent_wrappers(catalog: dict[str, dict[str, Any]], plugin_root: Path) -> list[Path]:
    """Claude Code plugin-bundled subagent wrappers. Package-only: Claude Code
    auto-discovers these from the installed plugin's agents/ directory, so they
    have no meaning outside it (unlike the Codex wrappers below).
    """
    written = []
    for agent_id, metadata in sorted(catalog.items()):
        inputs = role_wrapper_inputs(agent_id, metadata)
        definition = inputs["definition"]
        description = inputs["description"]
        profile = inputs["profile"]
        model = inputs["model"]
        reasoning_effort = inputs["reasoning_effort"]
        instructions = inputs["instructions"]

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
    return written


def codex_wrapper_contents(catalog: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Codex role wrappers as {filename: content}, for provider/codex-agents/.

    Codex has no plugin-bundled-agent mechanism: it discovers custom agents
    only from ~/.codex/agents/ or a project's .codex/agents/, never from a
    plugin manifest. These are therefore a tracked staging copy that `cadre
    bootstrap-codex` installs from -- which is why they live here, in the
    register, rather than only in the plugin package: the pip/pipx
    distribution vendors provider/ and must be able to serve bootstrap-codex
    without a plugin install. `cadre generate-role-metadata` writes and
    drift-checks them there; generate_provider_copy() then copies the same
    files into the package.

    Returns content rather than writing, so generate_role_metadata.py can fold
    these into the same rendered-content map it uses for catalog.yaml and
    routing.yaml and get --check for free.
    """
    contents: dict[str, str] = {}
    for agent_id, metadata in sorted(catalog.items()):
        inputs = role_wrapper_inputs(agent_id, metadata)
        definition = inputs["definition"]
        description = inputs["description"]
        profile = inputs["profile"]
        codex_model = inputs["codex_model"]
        reasoning_effort = inputs["reasoning_effort"]
        instructions = inputs["instructions"]

        # `model` uses catalog.yaml's separate `codex_model` OpenAI identifier, not
        # the Claude Code wrapper's haiku/sonnet/opus tier name -- the two
        # runners don't share a model-naming space. Re-verify these identifiers
        # against current Codex CLI docs before relying on them in automation.
        codex_agent_id = f"agents-{agent_id}"
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
        contents[f"{codex_agent_id}.toml"] = "\n".join(toml_lines)
    return contents


def derive_kind(definition: str) -> str:
    if definition.startswith("review/") or definition == "engineering/test-engineer/AGENT.md":
        return "reviewer"
    if definition.startswith("support/"):
        return "specialist"
    if definition in {"documentation/evidence-curator/AGENT.md", "knowledge-store/AGENT.md"}:
        return "specialist"
    return "author"


def agent_catalog_export_content(catalog: dict[str, dict[str, Any]]) -> str:
    """Package-relative catalog export consumed through provider.json.

    Written into this repository's own provider/ bundle for the same reason as
    generate_codex_wrappers() above: `cadre sdlc` must work from the pip/pipx
    distribution, which vendors provider/ but not the plugin package. The
    `definition` values stay package-relative (suite/agents/...) because
    provider.json resolves them inside an installed plugin; that is unchanged
    from before the register/plugin split.
    """
    agents = {
        agent_id: {
            "phase": metadata.get("phase", "unknown"),
            "kind": derive_kind(metadata["definition"]),
            "capabilities": (
                ["reviewer"]
                if derive_kind(metadata["definition"]) == "reviewer"
                else ["author", "dispatch"]
            ),
            "definition": f"{PROVIDER_DEFINITION_PREFIX}{metadata['definition']}",
        }
        for agent_id, metadata in sorted(catalog.items())
    }
    return json.dumps({"schema_version": 1, "agents": agents}, indent=2) + "\n"


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
    # select_agents.py (already packaged) imports this module directly, and
    # it is also its own packaged subcommand (selection-telemetry, see
    # bin/subcommands.tsv) -- it must ship even on a worktree where it is
    # still untracked/uncommitted, same carve-out as the two helpers above.
    telemetry_helper = "agents/orchestration/src/selection_telemetry.py"
    if (REPOSITORY_ROOT / telemetry_helper).is_file():
        tracked.add(telemetry_helper)
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
    # Same failure class as untracked_role_paths above, for
    # bin/subcommands.tsv instead of catalog.yaml: generate_bin_wrapper()
    # builds the packaged bin/cadre wrapper straight from
    # packaged_subcommands() (bin/subcommands.tsv), independently of
    # `tracked`/`selected` here. An untracked new subcommand script would
    # otherwise get a working case-statement entry in the wrapper while the
    # script itself silently never gets copied into suite/, producing a
    # package whose subcommand references a file that doesn't exist. Fail
    # loudly here instead, before either file is written.
    subcommands_table_path = REPOSITORY_ROOT / "bin" / "subcommands.tsv"
    subcommand_script_paths = (
        {script for _name, script in packaged_subcommands(REPOSITORY_ROOT) if script.startswith("agents/")}
        if subcommands_table_path.is_file()
        else set()
    )
    untracked_subcommand_scripts = subcommand_script_paths - tracked
    if untracked_subcommand_scripts:
        raise ValueError(
            "bin/subcommands.tsv references script(s) not tracked in git; "
            "commit them (git add) before regenerating the plugin: "
            + ", ".join(sorted(untracked_subcommand_scripts))
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
    # The packaged README is register-owned (PACKAGING_README) and rendered to
    # two places: the package root, where it is the repository's front page,
    # and suite/README.md, where the packaged docs cross-reference it.
    package_readme_content = PACKAGING_README.read_text(encoding="utf-8")
    write(plugin_root / "README.md", package_readme_content)
    written.append(plugin_root / "README.md")
    write(plugin_root / "suite" / "README.md", f"{GENERATED_MARKER}\n\n{package_readme_content}")
    written.append(plugin_root / "suite" / "README.md")
    for relative in selected:
        source = REPOSITORY_ROOT / relative
        target = plugin_root / "suite" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() == ".md":
            content = source.read_text(encoding="utf-8")
            content = content.replace("../bin/cadre", "../../bin/cadre")
            content = content.replace("../README.md", "README.md")
            content = content.replace("`../README.md`", "`README.md`")
            # The register's source for the packaged README (PACKAGING_README)
            # has no counterpart inside the package; point at the packaged
            # copy of it instead. Every file carrying this link sits one level
            # under suite/, so `../README.md` resolves to suite/README.md.
            content = content.replace("../packaging/plugin-README.md", "../README.md")
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
    return (
        generate_skill_copies(plugin_root)
        + generate_suite_copy(catalog, plugin_root)
        + generate_agent_wrappers(catalog, plugin_root)
        + generate_provider_copy(catalog, plugin_root)
        + [generate_bin_wrapper(plugin_root)]
    )


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
    # The package is written into a checkout of the plugin repository
    # (deagy/cadre-plugin). This repository has nothing to generate into, so
    # --output is required rather than defaulting anywhere -- a default would
    # silently create a stray directory here.
    if "--output" not in arguments:
        raise SystemExit(
            "cadre generate-plugin: --output is required. The packaged plugin lives in "
            "deagy/cadre-plugin; clone it and pass its root, e.g.\n"
            "    cadre generate-plugin --output /path/to/cadre-plugin"
        )
    output_index = arguments.index("--output")
    try:
        output_root = Path(arguments[output_index + 1]).resolve()
    except IndexError as error:
        raise SystemExit("--output requires a directory") from error
    if "--check" not in arguments and output_root.exists():
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
                [kernel, "--provider", str(PROVIDER_ROOT / "provider.json"), "provider", "list"],
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
