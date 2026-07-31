<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Cadre plugin

This self-contained plugin packages the repository's 49 specialist roles, nine
suite skills, orchestration runtime, knowledge-store runtime, and its external
Agentic SDLC provider (`provider.json` is the versioned source of truth — see
`version` and `kernel_compatibility` there rather than this prose). It does
not contain the lifecycle kernel; that remains a separately versioned
dependency.

The lifecycle kernel is maintained separately at
[`deagy/agentic-sdlc`](https://github.com/deagy/agentic-sdlc) and is not
installed as a Claude Code/Codex plugin — clone it and put its CLI on `PATH`
(or set `AGENTIC_SDLC_BIN`), then install this repository's own marketplace:

```sh
git clone https://github.com/deagy/agentic-sdlc.git
git -C agentic-sdlc checkout v0.3.0
export AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc
codex plugin marketplace add /path/to/cadre
codex plugin add cadre@cadre-team
```

For Claude Code:

```text
/plugin marketplace add /path/to/cadre
/plugin install cadre@cadre-team
```

`provider.json` contributes the `secure-cloud` profile, package-relative role
catalog, and optional impact extensions to Agentic SDLC v0.3.x. The repository
launcher injects it automatically:

```sh
AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc \
  cadre sdlc init --root /path/to/project --profile secure-cloud
```

The generated package contains no source-checkout paths. Role wrappers embed
their role and shared-policy instructions; skills and runtime files live under
`skills/` and `suite/`.

## GitHub review-backed approvals

The lifecycle commands are supplied by the standalone Agentic SDLC plugin and
are exposed here through `cadre sdlc`. To require GitHub reviews for human
gates, configure the target project's `.agentic-sdlc/project.json`:

```json
"approval_sources": {
  "human_gate_default": "github-review",
  "allow_manual_fallback": false
}
```

Bind each applicable authority to its GitHub login, then fetch and record an
approval with an authenticated GitHub CLI:

```sh
cadre sdlc approve-from-github-pr \
  --root /path/to/project --task-id TASK-42 --gate G2 \
  --role product_owner --repo OWNER/REPO --pr 42 --commit-sha "$GITHUB_SHA"
```

The command selects the latest matching `APPROVED` review and fails closed on
missing access, missing approval, identity mismatch, or revision mismatch. Run
`cadre sdlc validate` afterward. A valid approval advances the lifecycle
record to the next applicable gate; it does not approve deployment or accept
risk.

## Codex role wrappers

Codex discovers custom agents only under project `.codex/agents/` or global
`~/.codex/agents/`. Install the staged, namespaced wrappers safely:

```sh
cadre bootstrap-codex
```

The generated IDs and filenames use `agents-<role>`. The command
never touches legacy bare `<role>.toml` files and refuses to overwrite an
existing namespaced file unless it carries this generator's provenance marker.
Legacy bare global files may be removed manually after confirming nothing still
dispatches them; installation never deletes them. A project-local bare
`.codex/agents/<role>.toml` remains the preferred override.

Claude Code discovers `agents/*.md` directly from the plugin.

## Regeneration

Everything under `skills/`, `agents/`, `codex-agents/`, `suite/`,
`agent-catalog.json`, and `bin/cadre` is generated from tracked source:

```sh
cadre generate-plugin
```

`provider.json`, `profiles/`, and `extensions/` are maintained as provider
contracts. Repository health tests fail when generated content drifts.
