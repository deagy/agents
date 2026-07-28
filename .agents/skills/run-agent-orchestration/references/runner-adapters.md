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
  happens unless the MCP server below is registered, or the manual workaround
  is used. The same fallback is also the most plausible explanation for why a
  Codex-dispatched "agent" can appear to never close when its task finishes:
  a generic fallback thread is not an isolated child process the way a
  properly dispatched subagent is, so there would be nothing separate for
  Codex to wait on and reap. This repo cannot directly observe Codex CLI's
  own internal thread/process handling (no live `codex` binary available
  from inside this sandbox, same limitation as the TOML snippet below) — this
  is inference from the fallback behavior tracked in the issues above, not a
  confirmed root cause. What this repo *can* confirm and control:
  `dispatch_secure_cloud_role` below spawns a real, isolated child process
  and explicitly waits on it
  (`agents/orchestration/mcp/dispatch_core.py`'s `spawn_and_wait()`), which
  is a verified fix for the process-lifecycle question regardless of the
  above, not just for role selection.
  - **Preferred: register this repo's MCP dispatch server.**
    `agents/orchestration/mcp/dispatch_server.py` exposes a real
    `dispatch_secure_cloud_role` tool that resolves `role_id` to its `.toml`
    wrapper, extracts `developer_instructions`/`model`/`sandbox_mode` itself,
    enforces sandbox narrowing and a human confirmation gate for
    write-capable dispatch, and spawns the child in its own process group
    with an explicit wait/timeout/group-kill and a bounded concurrency
    limiter (see `agents/orchestration/mcp/SECURITY-CONTROLS.md` for exactly
    which of those guarantees are mechanically enforced and tested). Once
    registered, call it directly instead of `spawn_agent` — no per-file
    reading or manual `developer_instructions` injection needed. Setup:
    1. `pip install -r agents/orchestration/mcp/requirements-mcp.txt` (installs
       the official `mcp` SDK; stdio transport only — do not add a networked
       extra).
    2. Add a server entry to Codex CLI's `config.toml` (global
       `~/.codex/config.toml` or project-local `.codex/config.toml`) pointing
       at `agents mcp-dispatch-server` (repository-root `bin/agents`, resolves
       a Python 3.10+ interpreter the same way every other subcommand does) or
       directly at `python3 <repo>/agents/orchestration/mcp/dispatch_server.py`
       if `agents` isn't on `PATH`. The exact `[mcp_servers]` table syntax
       below is this suite's best current understanding of Codex CLI's config
       format and has not been verified against a live `codex` binary from
       inside this sandbox (no network/package access here) — verify against
       current Codex CLI docs before relying on it in production, matching
       this file's other unverified-Codex-specifics caveats:
       ```toml
       [mcp_servers.agents-dispatch]
       command = "agents"
       args = ["mcp-dispatch-server"]
       ```
    3. This server only ever spawns `codex exec` child processes for
       whichever role you dispatch; it does not itself replace or wrap your
       interactive Codex session.
  - **Fallback (only when the MCP server above is not registered): manual
    per-file injection instead of naming the custom agent to
    `spawn_agent`.** Read the target role's `.toml` file directly — project
    override first (`.codex/agents/<role-id>.toml`), else the synced global
    wrapper (`~/.codex/agents/agents-<role-id>.toml`), else this
    plugin's own `codex-agents/agents-<role-id>.toml` if sync
    hasn't run yet — and extract its `developer_instructions` string. Call
    `spawn_agent` with the generic `agent_type`, pass that
    `developer_instructions` text plus the task brief as the `prompt`
    argument, and pass the file's `model` value as the explicit `model`
    override (do not assume the tool infers either from a bare name). Report
    in the final summary that this per-file-injection fallback was used
    (rather than the MCP server), so it isn't mistaken for a properly closed
    dispatch — the "agent doesn't close on completion" symptom above applies
    to this fallback, not to the MCP path.
  - **A2A was evaluated as a fix for this exact limitation and rejected.** A2A
    is transport between separately-hosted agent processes; it cannot add a
    parameter to a running Codex session's `spawn_agent` tool surface, so it
    does not address this limitation at all.
- **Ordinary parallel wave**: request the same role set in one instruction
  (for example, "spawn one agent per role listed below"), applying the MCP
  dispatch tool (or, if it isn't registered, the manual-injection fallback)
  per role. Codex fans the requests out, waits for every result, and returns
  a consolidated response. Concurrency is bounded by the user's own
  `agents.max_concurrent_threads_per_session` (`[agents]` block in their
  `config.toml`) for native `spawn_agent` dispatch, and separately by this
  repo's own `MAX_CONCURRENT_CHILDREN` limiter when dispatched through the
  MCP server — this repo has no way to override the former from inside a
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

## Cline

`plugins/cline/` (this repo's hand-authored, non-generated Cline CLI plugin —
see `AGENTS.md`'s project-structure note) registers exactly one tool,
`agents_select`, which shells out to `./bin/agents select` and returns the
JSON dispatch plan. It is explicitly documented as "Plan only: never invokes
agents" and must stay that way (see `plugins/cline/index.ts`'s tool
description). **There is currently no
plugin-registered tool in this repo, and no supported one to add, that
actually dispatches a named role on Cline** — this is a confirmed gap, not an
oversight to route around silently:

- **Why a plugin can't dispatch.** A Cline plugin's `setup(api, ctx)` only
  receives `AgentExtensionApi`, whose surface is `registerTool`,
  `registerCommand`, `registerRule`, `registerMessageBuilder`,
  `registerProvider`, `registerAutomationEventType`, and `registerMcpServer`
  (verified against the installed `@cline/sdk`/`@cline/core` `0.0.65` type
  declarations under `plugins/cline/node_modules/@cline/core/dist/`, and
  against `docs.cline.bot/sdk/guides/writing-plugins`). None of those let a
  plugin spawn a sub-agent or teammate in the *current* session. The actual
  multi-agent primitives — `createSpawnAgentTool`, `AgentTeamsRuntime`,
  `createConfiguredAgentTools`, `bootstrapAgentTeams`, and the
  `team_spawn_teammate`/`team_run_task`/... tool family — live in
  `@cline/core` and are session-bootstrap primitives the **host** (the `cline`
  CLI itself, or an SDK app calling `ClineCore.create()`) uses to assemble a
  session's tool list before it starts; `@cline/agents`' own README says so
  directly ("For multi-agent workflows, use `@cline/core`" — plugins are not
  in that path). This is also consistent with the plugin sandbox
  architecture: a loaded plugin's `setup`/tool `execute` runs in an isolated
  subprocess that talks to the host only over the same
  `registerTool`/`executeTool` RPC calls (confirmed by reading the
  `@cline/core` bundle), so even a plugin tool's `execute()` body has no
  in-process handle to the running session's `AgentTeamsRuntime`.
- **Ordinary single-role dispatch today: manual injection, same shape as
  Codex's fallback below.** There is no Cline-native generated wrapper for
  this repo's roles yet — `.clinerules/` here holds one general pointer file
  to `AGENTS.md`/`agents/RUNBOOK.md`, not per-role definitions (see
  `AGENTS.md`'s project-structure note), and this repo does not generate
  `.cline/agents/*.yml` profiles (see "Cline's own native persona mechanism"
  below for why not, yet). Until that changes, an orchestrating Cline session
  must read the target role's definition itself — its plugin-generated Codex
  wrapper (`.codex/agents/<role-id>.toml`'s `developer_instructions`, or the
  global synced copy `~/.codex/agents/agents-<role-id>.toml`) is the most
  convenient already-flattened source, or `agents/<phase>/<role>/AGENT.md`
  directly for the canonical text — and inject that content as the task/system
  framing for a fresh chat turn or a spawned sub-agent
  (`use_subagents`/`enableSpawnAgent`, if the host session has that enabled).
  Report in the final summary that manual injection was used, exactly as the
  Codex section below asks, so it isn't mistaken for a mechanism that named
  the role directly.
- **Cline's own native persona mechanism exists but is not yet usable as a
  clean fix.** Cline has an in-progress "agent profiles" feature:
  `.cline/agents/*.yml` (workspace) or `~/.cline/agents/` (global) files with
  `name`/`description` frontmatter (plus, once the stack below lands,
  `tools`/`skills`/`providerId`/`modelId`/`plugins`) and a body used as the
  persona/system prompt. The installed `@cline/core@0.0.65` already contains
  the runtime pieces (`ConfiguredAgentConfig`, `loadConfiguredAgentConfigs`,
  `createConfiguredAgentTools`/`buildConfiguredAgentToolName`, confirmed by
  reading the bundled `.d.ts` files and finding a literal `"subagent_"`
  prefix in the compiled bundle) that expose each profile as a named
  `subagent_<name>` tool on the *main* agent's own toolset — but this is
  wired up by the host's session/runtime builder, not by a plugin, and as of
  this check (2026-07-28, verified via `gh pr view <n> -R cline/cline
  --json number,title,state,url`, not inferred) the CLI-facing completion of
  this feature (selecting a profile for the main agent and having its
  `tools`/`skills`/`providerId`/`modelId` actually take effect, not just its
  persona text) is tracked upstream as an open, unmerged PR stack —
  `cline/cline#11435` ("feat(sdk,cli): complete agent profiles support") →
  `#11448` ("feat(cli,sdk): agent profile plugin restrictions and cline agent
  install") → `#11505` ("feat(cli): wire up agent profile tools, skills,
  provider, and model for the main agent"), all `OPEN` at verification time —
  and there is no `docs.cline.bot` page for "agent profiles" yet (checked
  `/llms.txt`'s full index, not independently re-verified here). Re-check PR
  state before relying on this in production; it will go stale. Do not treat
  `.cline/agents/*.yml` as a reliable per-role dispatch
  path today; this is a documented future option once that stack merges and
  is verified live, not a current substitute for manual injection above.
  This repo does not generate these files (no `plugins/agents/cline-agents/`
  equivalent to `plugins/agents/codex-agents/*.toml` exists) — adding that
  generator is out of scope for this fix and would need its own design/review
  since it changes `agents generate-plugin`'s output surface.
- **`/team` (interactive) and `cline --team-name <name> "<mission>"` (CLI) are
  coordinator-prompt-driven, not persona-addressable.** Per
  `docs.cline.bot/cli/agent-teams` and `docs.cline.bot/sdk/guides/multi-agent-teams`,
  enabling team mode gives the coordinator agent additional tools
  (`team_spawn_teammate`, `team_delegate_task`/`team_run_task`,
  `team_check_status`/`team_status`, `team_get_result`) and the *coordinator's
  own model* decides which teammates to create, with what system prompt, and
  how to split the work — there is no CLI flag, `/team` argument, or SDK
  parameter that names a specific `agents:<role-id>` persona as a teammate.
  Team state (task board, mailbox, mission log) persists under
  `~/.cline/data/teams/[team-name]/` across sessions. For this skill's
  "Dispatch in Waves" / team-recipe cases (see
  [team-recipes.md](team-recipes.md)) on Cline:
  1. Start (or resume) the team with a mission prompt that explicitly lists
     the recipe's roles by name and pastes (or points at) each role's
     `AGENT.md` persona text/scope, since the coordinator has no other way to
     learn what `agents:security-reviewer` (for example) means on this repo.
  2. Verify after the fact — from `team_status`/the mission log, or the
     persisted `~/.cline/data/teams/[team-name]/mission-log.json` — that the
     coordinator actually spawned one teammate per requested role rather than
     collapsing the work into fewer generic teammates; nothing enforces the
     mapping.
  3. Treat `communication_mode: "peer"` as best-effort on Cline, not
     guaranteed the way it is on Claude Code's Agent Teams — the coordinator
     decides teammate-to-teammate messaging, not this skill or the plan.
- **No verified open Cline issue specifically requests a plugin-facing
  spawn/team-dispatch API.** Searched `cline/cline` issues/PRs for
  plugin+spawn/team-tool combinations; nothing on point beyond the agent
  profiles stack above was found — omitting a specific issue number here
  rather than inventing one, per this suite's policy on unverifiable
  citations.

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
