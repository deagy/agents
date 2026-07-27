# Runner Adapters

Translates "dispatch a subagent" and "run agents in parallel" (SKILL.md's
"Dispatch in Waves" section) into the concrete mechanism of whichever runner
is hosting this skill. Read this before dispatching the first agent of a
session, and again before proposing anything beyond an ordinary parallel
wave — see [team-recipes.md](team-recipes.md) for when that's warranted.

## Claude Code

- **Ordinary dispatch**: use the Agent tool, referencing the role by its
  generated subagent type. Plugin-installed: `agents:<role-id>`.
  Project-local override present (`.claude/agents/<role-id>.md`): bare
  `<role-id>`, per SKILL.md's existing dispatch-preference rule.
- **Ordinary parallel wave**: launch multiple Agent tool calls in one message.
  Each subagent has its own context window; results return only to this
  session. This is the default for SKILL.md's wave 2 ("independent
  implementation roles that can safely run in parallel").
- **Upgrading to an Agent Team**: when a wave's roles would genuinely benefit
  from challenging or building on each other's findings before you see a
  synthesized result — not just running in parallel — propose an agent team
  instead of ordinary subagents (see [team-recipes.md](team-recipes.md) for
  which recipes justify this):
  - Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` set in the user's
    `settings.json` `env` block or shell environment. This is experimental and
    off by default; if it isn't set, fall back to an ordinary parallel wave —
    a team cannot form without it.
  - Spawn each teammate by naming the same role-id subagent type used for
    ordinary dispatch (`agents:<role-id>` or project-local
    `<role-id>`, exactly as above). The teammate's system prompt is that
    definition's body plus its `tools`/`model` — assembled automatically once
    referenced by name, the same content ordinary dispatch already sends.
  - A teammate's `skills` and `mcpServers` frontmatter fields (should a
    definition ever set them) are not honored when spawned as a teammate —
    teammates load skills/MCP servers from project/user settings instead.
    This repo's generated wrappers don't currently set either field, so this
    is a forward-looking compatibility note, not a current blocker.
  - This orchestrating session remains the only one that talks to the human.
    A teammate that hits a human-only decision must still return a labeled
    blocking question rather than message the human directly — the same rule
    ordinary subagents follow, applied per-teammate.
  - Keep teams small (3–5 teammates) with disjoint file ownership per
    teammate — see `agents/shared/operating-principles.md`.
  - No nested teams: only the lead manages the team; a teammate cannot spawn
    its own teammates. This is a runner limitation, not a repo policy choice.

## Codex CLI

- **Ordinary dispatch**: custom agents are `.toml` files under
  `.codex/agents/` (project) or `~/.codex/agents/` (global) with `name`,
  `description`, `developer_instructions`, and optional `model` /
  `sandbox_mode` / `mcp_servers` — this repo's
  `plugins/agents/codex-agents/agents-*.toml`
  wrappers, safely synced into `~/.codex/agents/` per this skill's bootstrap
  step. Project-local bare role IDs remain preferred overrides.
- **Known upstream limitation — the model-visible dispatch tool cannot select
  a named custom agent.** As of current Codex CLI releases, the `spawn_agent`
  tool surface exposed to a running session accepts only a generic
  `agent_type` plus explicit `prompt`/`model` overrides; it has no parameter
  for "spawn the custom agent named `agents-<role>` from
  `.codex/agents/`" (tracked upstream as openai/codex#15250, #26363, #26408,
  #26828, #26868, #27061 — the regressed versions fall back silently to a
  generic thread that inherits the parent's model instead of erroring). This
  is why a Codex-hosted run of this skill can correctly select roles (`agents
  select` and the catalog are unaffected — selection is pure Python, not a
  Codex tool call) and then appear to stop: there is no tool argument that
  actually dispatches to the named role, so nothing beyond identification
  happens unless you use the workaround below.
  - **Workaround (do this instead of naming the custom agent to
    `spawn_agent`):** read the target role's `.toml` file directly — project
    override first (`.codex/agents/<role-id>.toml`), else the synced global
    wrapper (`~/.codex/agents/agents-<role-id>.toml`), else this
    plugin's own `codex-agents/agents-<role-id>.toml` if sync
    hasn't run yet — and extract its `developer_instructions` string. Call
    `spawn_agent` with the generic `agent_type`, pass that
    `developer_instructions` text plus the task brief as the `prompt`
    argument, and pass the file's `model` value as the explicit `model`
    override (do not assume the tool infers either from a bare name). Report
    in the final summary that this per-file-injection workaround was used, so
    it isn't mistaken for native named-agent dispatch.
  - **A2A was evaluated as a fix for this exact limitation and rejected.** A2A
    is transport between separately-hosted agent processes; it cannot add a
    parameter to a running Codex session's `spawn_agent` tool surface, so it
    does not address this limitation at all. The identified fix path is a
    Python MCP server, owned by this repo, exposing a dispatch tool Codex can
    call directly — in development, not yet available.
- **Ordinary parallel wave**: request the same role set in one instruction
  (for example, "spawn one agent per role listed below"), applying the
  workaround above per role. Codex fans the requests out, waits for every
  result, and returns a consolidated response. Concurrency is bounded by the
  user's own `agents.max_concurrent_threads_per_session` (`[agents]` block in
  their `config.toml`) — this repo has no way to override that from inside a
  project.
- **No team equivalent exists.** Codex's spawned subagents have no
  peer-to-peer messaging and no shared task list — coordination is entirely
  orchestrator-centric; Codex "waits until all requested results are
  available, then returns a consolidated response." Do not instruct a Codex
  session to "have the agents discuss with each other" — there is no
  mechanism for that.
- **Practical effect**: every recipe in team-recipes.md still works on
  Codex — the role list and each role's distinct focus are runner-agnostic —
  but the "teammates challenge each other" step degrades to "this
  orchestrating session reviews all N results and reconciles disagreements
  itself," since Codex has no way to let the roles do that directly.

## Team communication contract

`agents select` deterministically emits a `teams` array in its plan (see
[team-recipes.md](team-recipes.md) for the named recipes and
`agents/orchestration/routing.yaml`'s `team_recipes` for the trigger rules).
Every team entry carries `communication_mode: "peer"` and
`fallback: "orchestrator-relayed"` — this is not a choice made per dispatch,
it's a fixed statement of what's actually possible:

- **`peer`** is honored only on Claude Code with
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` set. Spawn the team's members as an
  Agent Team exactly as described above.
- **`fallback: orchestrator-relayed`** applies everywhere else — Codex always,
  and Claude Code whenever the experimental flag isn't set. Dispatch the same
  member list as an ordinary parallel wave and perform all reconciliation
  yourself as the orchestrating session. Never report that agents "discussed"
  or "challenged" each other's findings when this fallback was actually used —
  the consolidated report (see SKILL.md's "Consolidate Results") must name
  which mode actually ran for each team.

A `type: "dynamic"` team (the competing-hypotheses debugging recipe) only
supplies a `role` and an `instances: {min, max}` range — decide the actual
instance count and each instance's named hypothesis at dispatch time; the
selector can't know either in advance.

## Choosing between an ordinary wave and a team

Default to an ordinary parallel wave — it's cheaper and works identically on
both runners. Reach for a Claude Code Agent Team only when the recipe's value
specifically comes from teammates challenging or building on each other's
findings before you synthesize (see [team-recipes.md](team-recipes.md)), and
only when `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is available. On Codex, or on
Claude Code without that flag, run the same recipe as an ordinary wave and
perform the synthesis step yourself.
