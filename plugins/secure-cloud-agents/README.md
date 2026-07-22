# Secure Cloud Agents plugin

This plugin makes this repository's own agent suite — 34 specialist roles
(`agents/catalog.yaml`), 6 orchestration/authoring/knowledge skills
(`.agents/skills/`), and the shared knowledge store — reachable from any
project directory, not just this checkout, once installed at global/user
scope. See [`../agentic-sdlc/contracts/runner-adapters.md`](../agentic-sdlc/contracts/runner-adapters.md#system-wide-install)
for the general system-wide-install mechanism this relies on.

Unlike `plugins/agentic-sdlc/` — the portable lifecycle kernel meant to be
copied into other repositories — this suite is a single fixed instance that
belongs to this one checkout. Every file under `skills/`, `agents/`, and
`codex-agents/` here is a **generated, thin pointer**: it carries no
substantive content of its own, only this checkout's absolute path plus an
instruction to go read the real file there. That's a deliberate, necessary
tradeoff, not an oversight — see the module docstring in
[`../../agents/orchestration/src/generate_global_plugin.py`](../../agents/orchestration/src/generate_global_plugin.py)
for why (short version: installed plugins are cached by the runner, and a
relative path reaching outside the plugin's own directory stops resolving once
that happens).

## Install

Codex CLI (user-scoped by default):

```sh
codex plugin marketplace add .
codex plugin add secure-cloud-agents@agents-team
```

Claude Code (pass `--scope user` explicitly, or choose "user" when prompted):

```text
/plugin marketplace add .
/plugin install secure-cloud-agents@agents-team
```

This makes the 6 skills — and, in Claude Code, the 34 role subagents under
`agents/*.md` — available in every project you open afterward.

### Codex CLI: one extra step for subagents

Codex has no plugin-bundled-subagent mechanism; custom agents are only
discovered from `.codex/agents/` (project-scoped) or `~/.codex/agents/`
(global). The 34 `.toml` wrappers under `codex-agents/` in this plugin are a
repo-tracked staging copy — Codex does not load them from here directly. Make
them globally available once with:

```sh
mkdir -p ~/.codex/agents
cp plugins/secure-cloud-agents/codex-agents/*.toml ~/.codex/agents/
```

Re-run this copy step after regenerating (below) if you've added, removed, or
changed a role.

## Regenerating

Every file here is derived from `agents/catalog.yaml` and `.agents/skills/*/SKILL.md`.
Regenerate after adding/removing a role or skill, or if this checkout is ever
moved or renamed (the absolute paths baked into every pointer would otherwise
go stale):

```sh
python3 agents/orchestration/src/generate_global_plugin.py
```

`agents/orchestration/test/test_repository_health.py::test_secure_cloud_agents_plugin_is_generated_and_in_sync`
runs this and fails if the committed output doesn't match, so drift is caught
in CI rather than discovered later. Commit the regenerated files (and re-run
the Codex copy step above) as part of the same change that touched the role or
skill.

## Using it

Once installed, invoke `run-agent-orchestration` (or any of the other five
skills) from any project the same way you would from inside this checkout —
see `agents/RUNBOOK.md` in the source repository for worked examples. The
generated role subagents/wrappers already carry the ask-the-human rule from
`runner-adapters.md`: they will return a labeled blocking question rather than
attempt to prompt a human directly.

### Project-local overrides

Global-by-default doesn't mean every project has to use the global role or
knowledge store. See
[`../agentic-sdlc/contracts/runner-adapters.md`](../agentic-sdlc/contracts/runner-adapters.md#project-local-overrides)
for the full explanation; in short:

- **Roles**: give a project its own `.claude/agents/<role-id>.md` or
  `.codex/agents/<role-id>.toml` and `run-agent-orchestration` will dispatch
  that instead of the global `secure-cloud-agents:<role-id>` (Claude Code) or
  `~/.codex/agents/<role-id>.toml` copy (Codex) when working in that project.
- **Knowledge store**: give a project its own `.agents/knowledge-store/config.json`
  at its repository root and every command run from inside that project
  resolves to it automatically instead of the shared global store — see
  `agents/knowledge-store/README.md` for the full three-tier resolution
  (explicit `--config` > project-local > global) and the `--source` convention
  that keeps different projects' content distinguishable when they *do* use
  the shared store.
