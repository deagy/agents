# Runner Adapters

Translates "dispatch a subagent" and "run agents in parallel" (SKILL.md's
"Dispatch in Waves" section) into the concrete mechanism of whichever runner
is hosting this skill. Read this before dispatching the first agent of a
session, and again before proposing anything beyond an ordinary parallel
wave — see [team-recipes.md](team-recipes.md) for when that's warranted.

`roster/runner-capabilities.json` (validated by `roster/runner-capabilities.schema.json`)
is the machine-readable, build-time source of truth for eight closed-value
structural facts drawn from this file — generated-wrapper existence and
dispatch naming, `communication_mode: "peer"` support/gating and nested-team
support, named-agent-dispatch support and its workaround, and concurrency
bounds — one runner's values at a time under `runners.<runner-id>`. The
prose below is the narrative/investigative record (root-cause chains, issue
tracking, setup walkthroughs, epistemic caveats) that manifest cannot and
does not attempt to replace; where a structural fact and this prose overlap,
treat the manifest as authoritative for the *value* and this file as
authoritative for the *why*.

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
    teammate — see `roster/shared/operating-principles.md`.
  - No nested teams: only the lead manages the team; a teammate cannot spawn
    its own teammates. This is a runner limitation, not a repo policy choice.

## Codex CLI

- **Ordinary dispatch**: custom agents are `.toml` files under
  `.codex/agents/` (project) or `~/.codex/agents/` (global) with `name`,
  `description`, `developer_instructions`, and optional `model` /
  `sandbox_mode` / `mcp_servers` — this repo's
  `provider/codex-agents/agents-*.toml`
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
  (`roster/orchestration/mcp/dispatch_core.py`'s `spawn_and_wait()`), which
  is a verified fix for the process-lifecycle question regardless of the
  above, not just for role selection.
  - **Preferred: register this repo's MCP dispatch server.**
    `roster/orchestration/mcp/dispatch_server.py` exposes a real
    `dispatch_secure_cloud_role` tool that resolves `role_id` to its `.toml`
    wrapper, extracts `developer_instructions`/`model`/`sandbox_mode`/
    `model_reasoning_effort` itself,
    enforces sandbox narrowing and a human confirmation gate for
    write-capable dispatch, and spawns the child in its own process group
    with an explicit wait/timeout/group-kill and a bounded concurrency
    limiter (see `roster/orchestration/mcp/SECURITY-CONTROLS.md` for exactly
    which of those guarantees are mechanically enforced and tested). Once
    registered, call it directly instead of `spawn_agent` — no per-file
    reading or manual `developer_instructions` injection needed. Setup:
    1. `pip install -r roster/orchestration/mcp/requirements-mcp.txt` (installs
       the official `mcp` SDK; stdio transport only — do not add a networked
       extra).
    2. Add a server entry to Codex CLI's `config.toml` (global
       `~/.codex/config.toml` or project-local `.codex/config.toml`) pointing
       at `cadre mcp-dispatch-server` (repository-root `bin/cadre`, resolves
       a Python 3.10+ interpreter the same way every other subcommand does) or
       directly at `python3 <repo>/roster/orchestration/mcp/dispatch_server.py`
       if `cadre` isn't on `PATH`. The `[mcp_servers]` table syntax below
       (`command`/`args` keys) is verified against Codex CLI's live
       `config-reference` docs (2026-07-28) — `mcp_servers.<id>.command` and
       `mcp_servers.<id>.args` are documented config keys. Still unverified
       from inside this sandbox: actually registering and invoking this
       server through a live, authenticated `codex` session end to end (no
       API/ChatGPT credentials configured here) — that part still matches
       this file's other live-execution caveats:
       ```toml
       [mcp_servers.agents-dispatch]
       command = "agents"
       args = ["mcp-dispatch-server"]
       ```
    3. This server only ever spawns `codex exec` child processes for
       whichever role you dispatch; it does not itself replace or wrap your
       interactive Codex session.
    4. The same server also exposes `dispatch_team` for more than one role at
       once — call it with a `members` list (`{"role_id", "brief"}` per
       entry; duplicates of the same `role_id` are fine, e.g. several
       `debugging-engineer` instances pursuing distinct hypotheses) instead
       of looping `dispatch_secure_cloud_role` yourself. It returns only once
       every member has reached a terminal state, with each member's result
       distinguishable by `member_index`/`role_id`; a single team-wide
       `confirmation_required` round trip covers every write-capable member
       at once rather than one per member. See
       `roster/orchestration/mcp/SECURITY-CONTROLS.md`'s "Team dispatch"
       section for exactly how each single-role control (classification/
       sandbox narrowing, the depth guard, confirmation gating, the
       concurrency limiter, audit logging) generalizes to a team.
    5. `dispatch_secure_cloud_role`/`dispatch_team`/`dispatch_team_recipe` all
       accept an optional `runner` parameter (`"codex"`, the default and the
       only fully-verified option, or `"claude-code"`) for dispatching a
       role as a Claude Code child process instead of a Codex one. This is
       newer and only partially verified — read
       `roster/orchestration/mcp/SECURITY-CONTROLS.md`'s "Claude Code
       runner" section before relying on it: in particular, a Claude Code
       role can currently only ever be dispatched read-only (there's no
       wrapper-format field yet to declare write-capability the way a Codex
       `.toml` wrapper's `sandbox_mode` does), and the `--permission-mode`
       mapping this uses is a first-pass design choice, not a confirmed
       equivalent to Codex's `--sandbox`.
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
    override (do not assume the tool infers either from a bare name). If the
    file also sets `model_reasoning_effort`, pass it too if `spawn_agent`
    exposes a matching override in your Codex CLI version; if it doesn't,
    note the gap in the final summary rather than silently dropping the
    role's intended reasoning-effort tier. Report in the final summary that
    this per-file-injection fallback was used
    (rather than the MCP server), so it isn't mistaken for a properly closed
    dispatch — the "agent doesn't close on completion" symptom above applies
    to this fallback, not to the MCP path.
  - **Field-confirmed: a ChatGPT-authenticated Codex session can reject the
    `model` override outright, independent of which identifier is used.** A
    Codex session using this fallback reported `spawn_agent` rejecting *both*
    `gpt-5-codex` (sonnet-tier `codex_model`) and `gpt-5` (opus-tier) with
    "not supported," for two different roles in the same session. Wrapper
    resolution and `developer_instructions` injection both worked correctly
    up to that point; the rejection was specifically at spawn time on the
    explicit `model` argument. Two different tier identifiers failing
    identically in one session is more consistent with the account's
    authentication mode restricting *any* explicit model override (ChatGPT
    subscription auth ties a session to whatever model that plan already
    selected, as distinct from API-key auth, which does not) than with
    `catalog.yaml`'s `codex_model` values themselves being wrong — but this
    repo has no live `codex` binary and no way to confirm that distinction
    from inside this sandbox, so treat it as the leading hypothesis, not a
    verified root cause. If `spawn_agent` rejects the `model` argument as
    unsupported: retry the same call **without** the `model` argument at
    all, letting the session fall back to its own authenticated default
    model, and say so explicitly in the final summary (the role's
    instructions still ran correctly; only its catalog-specified model tier
    was not honored) — don't hard-fail the whole dispatch over a rejected
    model override when the role's instructions can still run under the
    session's default model. This exposure is not unique to this fallback:
    `dispatch_secure_cloud_role` (the preferred MCP path above) currently
    always passes the wrapper's `model` value to `codex exec` as an explicit
    `--model` flag with no fallback if the account rejects it
    (`roster/orchestration/mcp/dispatch_core.py`'s `build_child_argv`), so a
    ChatGPT-authenticated session hitting this would fail identically
    through the MCP path too — a code-level opt-out for that path is tracked
    as follow-up work, not yet implemented, since there is no confirmed exact
    `codex exec` failure signature to detect it against without guessing.
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

`cline/` in [`deagy/cadre-lifecycle`](https://github.com/deagy/cadre-lifecycle) (the
hand-authored, non-generated Cline CLI plugin —
see `AGENTS.md`'s project-structure note) registers exactly one tool,
`agents_select`, which shells out to `./bin/cadre select` and returns the
JSON dispatch plan. It is explicitly documented as "Plan only: never invokes
agents" and must stay that way (see that repository's `cline/index.ts` tool
description). **There is currently no
plugin-registered tool in this repo, and no supported one to add, that
actually dispatches a named role on Cline** — this is a confirmed gap, not an
oversight to route around silently. A working, *non*-plugin path exists
today, and as of this section's most recent live re-verification it is now
usable end to end — see "MCP registration works for discovery and, as of
CLI 3.0.51 / `@cline/core` 0.0.71, for a real dispatch too" below before
falling back to manual injection:

- **MCP registration works for discovery and, as of CLI 3.0.51 /
  `@cline/core` 0.0.71, for a real dispatch too — re-verified live,
  2026-08-06, superseding the 2026-08-05 finding below.** MCP server
  registration is a host-level Cline feature (`cline mcp add`/the MCP add
  wizard, writing to `~/.cline/data/settings/cline_mcp_settings.json`),
  independent of `AgentExtensionApi` and its `registerTool` limitation below
  — so the same `dispatch_secure_cloud_role`/`poll_dispatch_status`/
  `dispatch_team`/`poll_team_status`/`dispatch_team_recipe` server documented
  for Codex CLI above *can* be registered for Cline too, from a full source
  checkout (not the packaged plugin — `roster/orchestration/mcp/dispatch_server.py`
  and its `requirements-mcp.txt` pin are only present there):
  1. `cline mcp add --yes agents-dispatch -- <repo>/bin/cadre
     mcp-dispatch-server` registers cleanly with no warnings, and a live
     act-mode `cline` session correctly lists all five tools in its toolset,
     namespaced `agents-dispatch__dispatch_secure_cloud_role`,
     `agents-dispatch__poll_dispatch_status`, `agents-dispatch__dispatch_team`,
     `agents-dispatch__poll_team_status`,
     `agents-dispatch__dispatch_team_recipe` (`poll_dispatch_status`/
     `poll_team_status` are new since the 2026-08-05 finding below — see
     "Async dispatch now exists as its own mitigation" further down).
  2. A real call needs one more piece registration doesn't set up: the
     server refuses every dispatch until its own process env has
     `SECURE_CLOUD_AGENTS_PARENT_CLASSIFICATION` set (fail-closed, not a
     bug) — still true and unchanged. `cline mcp add` has no flag for server
     env vars; set it by hand-editing an `"env"` object into the registered
     server's `transport` block in `cline_mcp_settings.json`
     (`McpStdioTransportConfig` in `@cline/core`'s types confirms `env`
     belongs there, sibling to `command`/`args`), e.g. `"env": {
     "SECURE_CLOUD_AGENTS_PARENT_CLASSIFICATION": "internal"}`.
  3. **The 2026-08-05 hardcoded-5000ms-timeout finding is now stale and
     fixed.** Re-checked live against the environment's actually-installed
     Cline (CLI 3.0.51, `@cline/core`/`@cline/shared` 0.0.71 — newer than the
     CLI 3.0.47 / 0.0.65 the original finding was verified against): the
     literal string `"MCP request timed out"` is no longer present in the
     `@cline/core` bundle at all. `@cline/shared`'s exported
     `DEFAULT_MCP_TIMEOUT_SECONDS` is now **60** (was an unconfigurable
     hardcoded 5), and `resolveMcpTimeoutSeconds()` reads a per-server
     override, confirmed by the current timeout error message itself:
     `MCP request to "<server>" ... timed out after <N>s. Increase the
     "timeout" field (in seconds) for this server in
     cline_mcp_settings.json.` A live, real, end-to-end
     `dispatch_secure_cloud_role` call for `code-reviewer` (default
     `planning-review-only` mode, `runner="codex"`, `wait=true`) **completed
     successfully through Cline's actual MCP client**, no timeout: the
     dispatch server's own result reported `"timed_out": false,
     "duration_seconds": 18.41` — well past the old hardcoded 5s ceiling and
     comfortably inside the new 60s default. (The dispatched `codex exec`
     child itself exited 1 in this sandbox, unrelated to MCP/Cline — a
     `402 deactivated_workspace` from the Codex backend, a credentials issue
     with the test account, not a dispatch-path failure.) No orphaned
     `dispatch_server.py`/`codex exec` process was left behind afterward.
  - **Net effect (updated):** this path now gives you tool discovery, fast
    fail-closed checks (like the classification denial), *and* a completed
    end-to-end dispatch through Cline's native MCP client, at least for a
    task finishing within the (overridable) 60s default. Treat
    `dispatch_secure_cloud_role`/`dispatch_team`/`dispatch_team_recipe` as
    **usable end to end from Cline** on a current Cline install; only fall
    back to manual injection below if either (a) your installed Cline
    predates CLI ~3.0.5x / `@cline/core` ~0.0.7x and still carries the old
    hardcoded timeout (check your own installed
    `@cline/shared/dist/index.js` for `DEFAULT_MCP_TIMEOUT_SECONDS` before
    assuming either way), or (b) a real task genuinely needs longer than the
    configured "timeout" field allows and raising it isn't an option — in
    which case prefer the async `wait=false` + `poll_dispatch_status` path
    described next over reverting to manual injection.
  - **Async dispatch now exists as its own mitigation, independent of
    Cline's client timeout.** `dispatch_secure_cloud_role` gained a `wait`
    parameter (default `true`, unchanged behavior) documented in its own
    tool description: `wait=false` returns immediately with
    `{"status": "dispatched_async", "job_id": ...}` and moves the slow
    child-process wait to a background thread server-side; poll the result
    with `poll_dispatch_status(job_id)`, which returns `{"status":
    "not_found"}`, `{"status": "running", ...}`, or the same result shape
    `wait=true` returns directly once finished. This was added specifically
    for "your MCP client has a short, non-configurable tools/call timeout"
    per its own docstring — with Cline's timeout now both longer and
    configurable, `wait=true` is fine for most real dispatches, but prefer
    `wait=false`+polling for a task expected to run well past 60s rather
    than raising the per-server "timeout" field indefinitely.
- **Why a plugin can't dispatch.** A Cline plugin's `setup(api, ctx)` only
  receives `AgentExtensionApi`, whose surface is `registerTool`,
  `registerCommand`, `registerRule`, `registerMessageBuilder`,
  `registerProvider`, `registerAutomationEventType`, and `registerMcpServer`
  (verified against the installed `@cline/sdk`/`@cline/core` `0.0.65` type
  declarations under that plugin's `node_modules/@cline/core/dist/`, and
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
- **Fallback path when the MCP dispatch server isn't registered, or is
  registered against a Cline install predating the timeout fix above:
  manual injection, same shape as Codex's fallback below.** Prefer
  registering the MCP dispatch server (above) on a current Cline install —
  it now completes a real dispatch end to end, per the re-verification
  above — and reach for manual injection only when that's unavailable.
  There is no Cline-native generated wrapper for
  this repo's roles yet — `.clinerules/` here holds one general pointer file
  to `AGENTS.md`/`roster/RUNBOOK.md`, not per-role definitions (see
  `AGENTS.md`'s project-structure note), and this repo does not generate
  `.cline/roster/*.yml` profiles (see "Cline's own native persona mechanism"
  below for why not, yet). Until that changes, an orchestrating Cline session
  must read the target role's definition itself — its plugin-generated Codex
  wrapper (`.codex/agents/<role-id>.toml`'s `developer_instructions`, or the
  global synced copy `~/.codex/agents/agents-<role-id>.toml`) is the most
  convenient already-flattened source, or `roster/<phase>/<role>/AGENT.md`
  directly for the canonical text — and inject that content as the task/system
  framing for a fresh chat turn or a spawned sub-agent
  (`use_subagents`/`enableSpawnAgent`, if the host session has that enabled).
  Report in the final summary that manual injection was used, exactly as the
  Codex section below asks, so it isn't mistaken for a mechanism that named
  the role directly.
- **Cline's own native persona mechanism exists but is not yet usable as a
  clean fix.** Cline has an in-progress "agent profiles" feature:
  `.cline/roster/*.yml` (workspace) or `~/.cline/roster/` (global) files with
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
  `.cline/roster/*.yml` as a reliable per-role dispatch
  path today; this is a documented future option once that stack merges and
  is verified live, not a current substitute for manual injection above.
  This repo does not generate these files (no `cline-roster/` equivalent to
  `provider/codex-agents/*.toml` exists) — adding that
  generator is out of scope for this fix and would need its own design/review
  since it changes `cadre generate-plugin`'s output surface.
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

`cadre select` deterministically emits a `teams` array in its plan (see
[team-recipes.md](team-recipes.md) for the named recipes and
`roster/orchestration/routing.yaml`'s `team_recipes` for the trigger rules).
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
