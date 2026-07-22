# Agentic SDLC plugin

This plugin makes the repository's G1–G10 Agentic SDLC portable. It supplies a versioned lifecycle kernel, deterministic planning and validation tools, and skills packaged for both Codex CLI and Claude Code, while leaving project-specific authority and lifecycle state in the target repository. See [runner-adapters.md](contracts/runner-adapters.md) for exactly how each runner maps to skill invocation, human questions, and subagent dispatch.

The intended adoption path is:

```text
Install plugin -> initialize target repository -> review detected overlay
-> assign human authorities and resolve applicability -> plan or orchestrate work
```

Initialization makes a project immediately usable for planning, artifact preparation, independent review, and validation. It does not make unresolved organizational decisions merely to produce a green result.

## Install from the team marketplace

Two equivalent marketplace manifests point at the same plugin: `.agents/plugins/marketplace.json` for Codex CLI and `.claude-plugin/marketplace.json` for Claude Code, both named `agents-team`. From this repository root, add the marketplace and install the plugin:

Codex CLI:

```sh
codex plugin marketplace add .
codex plugin add agentic-sdlc@agents-team
```

Claude Code:

```text
/plugin marketplace add .
/plugin install agentic-sdlc@agents-team
```

If your team publishes this marketplace from a shared Git source, use that marketplace source instead of the local checkout. Installation exposes the bundled skills (and, once a target project is initialized, the generated subagent wrappers); it does not edit a target repository.

## Initialize a project

The repository-hosted development command is (`bin/agents` at this repository's
root resolves the interpreter and dispatches to `scripts/agentic_sdlc.py`;
`agents sdlc ...` works from any directory once it's on `PATH` — see
`../../README.md` "System-wide install"):

```sh
agents sdlc init --root /path/to/target
```

From an installed plugin, invoke the `initialize-agentic-sdlc` skill and identify the target repository. The skill detects candidate stack and command information, calls the initializer, preserves unknowns and unassigned authorities, and then runs validation. The CLI `init` command itself writes the overlay and reports blockers; run `validate` separately when using the CLI directly. Review generated files before using them as policy.

Use `--help` for the exact options supported by the installed plugin version:

```sh
agents sdlc init --help
```

## Portable architecture

The distribution has three deliberately separate layers:

| Layer | Owner | Contents |
|---|---|---|
| Portable kernel | Plugin maintainer | G1–G10 definitions, mutation-gate separation, schemas, agent catalog, selector/validator behavior, and reusable skills. |
| Project overlay | Target project | Technology and command detection, routing/profile choices, authority assignments, environment declarations, applicability decisions, and kernel version lock. |
| Project state | Target project | Dispatch plans, run records, findings, exceptions, invalidations, evidence references, and human approval references. |

The plugin may be upgraded independently. It never becomes the authoritative location for a project's decisions or evidence.

Initialization creates or manages this target-repository structure:

```text
.agentic-sdlc/
├── project.json
├── authorities.json
├── impact-profile.json
├── routing.json
├── commands.json
├── version.lock
└── runs/<task-id>/
    ├── dispatch-plan.json
    └── run-record.json
.codex/agents/                 # Profile-selected project agent wrappers (Codex CLI)
.claude/agents/                # Profile-selected project agent wrappers (Claude Code)
AGENTS.md                      # Small managed Agentic SDLC instruction block
```

`init --runner {codex,claude,both}` (default `both`) controls which wrapper set is generated; both are safe to keep even if only one runner is in active use. Existing custom agent wrapper files are not overwritten. Use `init --force` only after reviewing its help: it refreshes managed overlay files and can replace project decisions stored in those managed files.

## Safe defaults

Initialization and orchestration fail closed where a correct decision cannot be derived from repository content:

- Human decision authorities start unassigned unless explicitly configured.
- Conditional authorities for data/control ownership, key ownership, UAT, and
  runtime-implicated Security or Governance Leads start with `unknown`
  applicability. Marking one `not-applicable` requires an accountable rationale.
- Compliance, jurisdiction, specialized BOM, and extension applicability remain `unknown` until an accountable owner decides them.
- Environments are not assumed disposable, persistent, or production from a name alone.
- No gate is approved by initialization, detection, planning, or validation.
- Quality-gate readiness never substitutes for production, destructive, persistent-migration, privileged-identity, exception, or risk-acceptance authorization.
- Unknown applicable requirements block the affected gate instead of being treated as not applicable.

These defaults allow work products to be prepared immediately while preventing an incomplete bootstrap from silently granting authority.

## Profiles and extensions

A profile supplies candidate routing, artifact, gate, and validation defaults for a recognizable project shape. The current kernel includes `quick`, `generic`, and `web-service`; `--profile auto` proposes one from observable repository files, favoring `quick` absent a stronger signal. A human reviews the result. Check `init --help` because later releases may add profiles.

`quick` is the recommended starting point for "give it a task and let it orchestrate" use: a small agent set, and routes that carry no required G1-G10 lifecycle gate. `mutation-gates.json` is evaluated independently of profile, so production, destructive, persistent-migration, privileged-identity, and risk-acceptance requests still stop for human approval no matter which profile is active. `generic` and `web-service` are the heavier, opt-in profiles for teams that want the full lifecycle-gate ceremony from the start; see `agents/orchestration/quality-gates.md` in the source repository for what G1-G10 mean.

SQS is an optional impact-profile extension, not a requirement of the portable kernel. Enable it during initialization with `--extension sqs-platform`. Projects that enable it receive the SQS category and specialized BOM applicability questions. Projects that do not use SQS retain the generic lifecycle; they should record the extension as not applicable with an owner and rationale when organizational policy requires that decision. Enabling SQS never supplies missing definitions: unresolved applicable terms remain `unknown` and block their affected gates.

## Commands

The bundled command entry point is `plugins/agentic-sdlc/scripts/agentic_sdlc.py`:

```text
init        Create or update a project overlay using safe defaults.
detect      Inspect a repository and report candidate project characteristics.
plan        Produce a reviewable dispatch plan for a task.
validate    Validate the overlay and lifecycle records.
status      Report lifecycle and gate state for a task.
invalidate  Record a material change and invalidate the earliest affected gate and its dependents.
```

Always inspect command-specific help before scripting an interface:

```sh
agents sdlc --help
agents sdlc plan --help
```

Task IDs are preserved exactly and must already use only letters, numbers, dots, underscores, and hyphens. The CLI rejects lossy normalization so distinct external IDs cannot share lifecycle state.

Representative invocations are:

```sh
agents sdlc detect --root /path/to/target
agents sdlc init --root /path/to/target --profile auto --classification internal
agents sdlc plan --root /path/to/target --task-id TEAM-DEMO-001 --task "Define requirements traceability for the order API"
agents sdlc validate --root /path/to/target
agents sdlc status --root /path/to/target --task-id TEAM-DEMO-001
agents sdlc invalidate --root /path/to/target --task-id TEAM-DEMO-001 --earliest-gate G2 --reason "Approved intent changed" --actor "product-owner"
```

`validate` exits with `0` when valid and ready, `2` when structurally valid but blocked by unresolved decisions, and `1` for errors. Treat both `1` and `2` as non-ready in CI.

Initialization, detection, planning, status, and invalidation work with Python 3.10+ and the standard library. Install the pinned validation dependencies before using `validate`; validation fails closed when they are absent. Enable complete Draft
2020-12 structural validation in CI or assurance environments with:

```sh
python3 -m pip install -r plugins/agentic-sdlc/requirements-validation.txt
```

The plugin also exposes these skills, packaged for both Codex CLI and Claude Code:

- `initialize-agentic-sdlc`
- `orchestrate-agentic-sdlc`
- `validate-agentic-sdlc`
- `review-lifecycle-gate`
- `invalidate-lifecycle-gates`
- `runtime-assurance-status`

Use a skill for the guided workflow and the command for deterministic generation, inspection, validation, and CI integration.

## Team demonstration

Use a synthetic or non-production repository for the first demonstration:

1. Install the plugin and initialize the repository.
2. Show the generated unknown/unassigned values and explain why they fail closed.
3. Use `detect` to review observable stack and command candidates.
4. Use `plan` for an intent-and-requirements task and inspect the selected workflow, agents, `required_quality_gates`, and separate `human_gates`.
5. Invoke `orchestrate-agentic-sdlc` in planning-review-only mode.
6. Show that artifact authors, independent reviewers, and human approvers remain separate.
7. Validate and display the project-owned run record.
8. Change a material upstream assumption and demonstrate downstream invalidation without granting a new approval.

A suitable prompt is (see [runner-adapters.md](contracts/runner-adapters.md) for the `$skill-name` vs `/skill-name` distinction):

```text
Use orchestrate-agentic-sdlc in planning-review-only mode.
Task ID: TEAM-DEMO-001
Objective: Define and review a small internal order-processing API.
Prepare intent, traceable requirements, architecture, governance/data,
security/crypto, test, and evidence obligations. Do not deploy or approve gates.
```

A basic prompt also works without a task ID, classification, or explicit mode —
the skill derives them and asks only when something is genuinely ambiguous:

```text
Use orchestrate-agentic-sdlc to review whether the order-processing API is ready to ship.
```

## Upgrades and version lock

The generated overlay records both the kernel and plugin versions it was created against. Treat that lock as a compatibility declaration, not as proof that the project has adopted a newer lifecycle.

For an upgrade:

1. Update or reinstall the plugin from the same marketplace.
2. Review release and schema changes before changing the project lock.
3. Run `detect` and `validate` against the existing overlay and records.
4. Review any generated overlay differences; do not overwrite local authority or applicability decisions without an accountable owner.
5. Migrate incompatible records explicitly, rerun validation, and commit the lock change with the reviewed overlay changes.

Keep lifecycle state in version control according to the project's evidence-classification and retention rules. Do not commit secrets or raw approval credentials.

## Current limitations

- The development CLI requires Python 3.10 or newer; standalone executables are not bundled.
- Detection is advisory and inspects repository-root signatures rather than deeply evaluating every component. Candidate commands are not automatically trusted or executed.
- It cannot identify human authorities, legal obligations, risk acceptance, evidence-retention policy, or production authorization.
- The portable validator fails closed unless `requirements-validation.txt` is installed. With it, validation enforces lifecycle safety semantics and exhaustive Draft 2020-12 structural and format validation against the bundled schemas; CI enables this mode.
- The plugin prepares and validates decision records but does not authenticate an approver's real-world identity; projects must reference evidence from their authoritative approval system.
- It does not deploy, apply infrastructure, run persistent migrations, accept risk, merge, or approve gates.
- Project-specific agent wrappers, knowledge-store integrations, CI wiring, and organization-specific impact extensions may require an overlay customization.
- Specialized SQS/BOM semantics remain unavailable until an authorized owner supplies definitions and applicability.

For the full lifecycle criteria and the source suite's operating model, see `agents/orchestration/quality-gates.md` and `agents/RUNBOOK.md` in this repository.
