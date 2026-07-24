# Secure Cloud Agents plugin

This self-contained plugin v0.3.0 packages the repository's 34 specialist
roles, six suite skills, orchestration runtime, knowledge-store runtime, and
its external Agentic SDLC provider. It does not contain the lifecycle kernel;
that remains a separately versioned dependency.

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
catalog, and optional impact extensions to Agentic SDLC v0.3.x. The repository
launcher injects it automatically:

```sh
AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc \
  agents sdlc init --root /path/to/project --profile secure-cloud
```

The generated package contains no source-checkout paths. Role wrappers embed
their role and shared-policy instructions; skills and runtime files live under
`skills/` and `suite/`.

## GitHub review-backed approvals

The lifecycle commands are supplied by the standalone Agentic SDLC plugin and
are exposed here through `agents sdlc`. To require GitHub reviews for human
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
agents sdlc approve-from-github-pr \
  --root /path/to/project --task-id TASK-42 --gate G2 \
  --role product_owner --repo OWNER/REPO --pr 42 --commit-sha "$GITHUB_SHA"
```

The command selects the latest matching `APPROVED` review and fails closed on
missing access, missing approval, identity mismatch, or revision mismatch. Run
`agents sdlc validate` afterward. A valid approval advances the lifecycle
record to the next applicable gate; it does not approve deployment or accept
risk.

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
