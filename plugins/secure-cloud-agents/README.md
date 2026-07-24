# Secure Cloud Agents plugin

This self-contained plugin packages the repository's 34 specialist roles, six
suite skills, orchestration runtime, knowledge-store runtime, and its external
Agentic SDLC provider.

The lifecycle kernel is maintained separately at
[`deagy/agentic-sdlc`](https://github.com/deagy/agentic-sdlc). Install that
plugin first, then install this repository's marketplace:

```sh
codex plugin marketplace add /path/to/agentic-sdlc
codex plugin add agentic-sdlc@agentic-sdlc
codex plugin marketplace add /path/to/agents
codex plugin add secure-cloud-agents@agents-team
```

For Claude Code:

```text
/plugin marketplace add /path/to/agentic-sdlc
/plugin install agentic-sdlc@agentic-sdlc
/plugin marketplace add /path/to/agents
/plugin install secure-cloud-agents@agents-team
```

`provider.json` contributes the `secure-cloud` profile, package-relative role
catalog, and optional impact extensions to Agentic SDLC v0.2.x. The repository
launcher injects it automatically:

```sh
AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc \
  agents sdlc init --root /path/to/project --profile secure-cloud
```

The generated package contains no source-checkout paths. Role wrappers embed
their role and shared-policy instructions; skills and runtime files live under
`skills/` and `suite/`.

## Codex role wrappers

Codex discovers custom agents only under project `.codex/agents/` or global
`~/.codex/agents/`. Copy the staged wrappers after installation:

```sh
mkdir -p ~/.codex/agents
cp plugins/secure-cloud-agents/codex-agents/*.toml ~/.codex/agents/
```

Claude Code discovers `agents/*.md` directly from the plugin.

## Regeneration

Everything under `skills/`, `agents/`, `codex-agents/`, `suite/`,
`agent-catalog.json`, and `bin/agents` is generated from tracked source:

```sh
agents generate-plugin
```

`provider.json`, `profiles/`, and `extensions/` are maintained as provider
contracts. Repository health tests fail when generated content drifts.
