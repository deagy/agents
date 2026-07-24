# Secure Cloud Agents

This repository contains a secure cloud agent suite. It is intended for teams building self-hosted infrastructure and applications with Proxmox, Talos, Kubernetes, Helm, Terraform, GitLab CI/CD, Go, PostgreSQL, React, TypeScript, Python where useful, and Gherkin-based integration/regression testing.

The agent suite helps select, coordinate, test, review, document, support, and escalate work across specialized roles. Agents may prepare scoped repository changes and evidence, but human approval is still required for production, persistent infrastructure, destructive actions, policy exceptions, privileged access, and risk acceptance.

## Repository layout

```text
.
├── AGENTS.md                 # Repository-wide contributor and safety rules
├── bin/agents                # CLI dispatcher for every Python tool below (bin/agents.ps1 for PowerShell)
├── agents/                   # Agent roles, policies, workflows, orchestration, support, tests
├── .agents/skills/           # Publishable skills for this repository (Codex CLI; pointed to from .claude/skills/)
├── .agents/plugins/          # Codex CLI repository/team marketplace metadata
├── .claude/skills/           # Thin pointers to .agents/skills/* for Claude Code discovery
├── .claude-plugin/           # Claude Code repository/team marketplace metadata
├── plugins/secure-cloud-agents/ # Self-contained suite and Agentic SDLC provider
├── .github/workflows/        # Validate-only GitHub Actions pipeline (tests, bin/agents smoke test, secret scan)
├── docs/                     # Audience-oriented guides and human-readable role index
├── IDENTITY.md               # Informational suite identity; never an authority source
├── CONTRIBUTING.md           # GitHub contribution and review workflow
└── README.md                 # This overview
```

## Choose your path

| Goal | Start here |
| --- | --- |
| Understand the suite | [IDENTITY.md](IDENTITY.md), then [documentation index](docs/README.md) |
| Use the suite from a checkout | [Getting started](docs/getting-started.md) |
| Select and coordinate agents | [Orchestration guide](docs/orchestration.md) |
| Initialize lifecycle gates in another project | [Lifecycle and plugin operations](docs/lifecycle-and-plugin-operations.md) |
| Find the right specialist | [Role index](docs/role-index.md) |
| Contribute here | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Operate the full system | [agents/RUNBOOK.md](agents/RUNBOOK.md) |

Key areas:

- [bin/agents](bin/agents) dispatches the suite tools (`agents select`, `agents knowledge`, `agents sdlc`, and `agents generate-plugin`); lifecycle validation is provided by the standalone `agentic-sdlc` CLI.
- [agents/catalog.yaml](agents/catalog.yaml) is the machine-readable role inventory.
- [agents/RUNBOOK.md](agents/RUNBOOK.md) explains how to select, dispatch, review, and escalate agent work.
- [agents/orchestration/](agents/orchestration/) contains routing rules, lifecycle applicability mappings, handoff contracts, escalation policy, selectors, and tests.
- [agents/shared/](agents/shared/) contains operating principles, autonomy policy, technology standards, library standards, knowledge-store rules, and risk guidance.
- [agents/workflows/](agents/workflows/) defines workflows for new services, infrastructure, CI/CD, releases, rollback, knowledge ingestion, and support escalation.
- [agents/knowledge-store/](agents/knowledge-store/) contains the retrieval layer for approved historical context.
- [agents/testing/](agents/testing/) and [agents/support/](agents/support/) define black-box testing, end-user testing, support triage, and escalation roles.
- [.agents/skills/](.agents/skills/) contains this repository's skills, packaged for Codex CLI directly and pointed to from `.claude/skills/` for Claude Code.
- [deagy/agentic-sdlc](https://github.com/deagy/agentic-sdlc) owns the portable lifecycle kernel, initializer, validator, and lifecycle skills.
- [plugins/secure-cloud-agents/](plugins/secure-cloud-agents/) packages this suite, its 34 roles, and the external `secure-cloud` provider profile.

The boundary is intentional: Agentic SDLC owns lifecycle state, schemas, gate
transitions, approval-source policy, and portable commands. This repository
owns the Secure Cloud role catalog, role policies, workflows, knowledge store,
and the `secure-cloud` provider. A target project records its own decisions
and run state under `.agentic-sdlc/`; installing or upgrading a plugin does not
grant approval or rewrite those records.

## Supported runners

Every role definition and orchestration tool is runner-neutral text and data. Codex CLI and Claude Code wrappers are generated into the self-contained Secure Cloud plugin. Lifecycle contracts and runner adapters are versioned by [Agentic SDLC](https://github.com/deagy/agentic-sdlc).

## Quick start

Read [AGENTS.md](AGENTS.md) first, then use the [getting-started guide](docs/getting-started.md). `bin/agents` resolves a Python 3.10+ interpreter for you (checks `python3`/`python`; `.\bin\agents.ps1` also checks `py -3` in PowerShell) — see "Put `agents` on `PATH`" to put it on `PATH`, or run it as `./bin/agents` (`.\bin\agents.ps1` in PowerShell) from the repository root. Then validate the suite-only component and, when the standalone lifecycle executable is available, the orchestration tools:

```sh
python3 -m unittest discover -s agents/knowledge-store/test -p "test_*.py"
# AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc \
#   python3 -m unittest discover -s agents/orchestration/test -p "test_*.py"
```

Generate a reviewable dispatch plan:

```sh
agents select \
  --task "Review a React and Go upload feature" \
  --files frontend/src/App.tsx,services/internal/api/api.go \
  --classification internal \
  --task-id EXAMPLE-1
```

The selector emits a plan only. It does not run agents, retrieve knowledge, deploy, mutate infrastructure, merge, push, or approve anything.

## Agentic SDLC quick start

Install the reusable G1-G10 lifecycle from its standalone repository, then use
this suite's compatibility command to inject the Secure Cloud provider. Pin
the standalone repository to a reviewed release in automation; `main` is useful
for exploration but is not an immutable dependency:

```sh
git clone https://github.com/deagy/agentic-sdlc.git
git -C agentic-sdlc checkout v0.2.0
codex plugin marketplace add ./agentic-sdlc
codex plugin add agentic-sdlc@agentic-sdlc
```

Claude Code:

```text
/plugin marketplace add ./agentic-sdlc
/plugin install agentic-sdlc@agentic-sdlc
```

Put `agentic-sdlc/bin/agentic-sdlc` on `PATH`, or set
`AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc`, then run
`agents sdlc init --root /path/to/target`.

This defaults to the low-ceremony `quick` profile and generates subagent wrappers for both runners (`init --runner {codex,claude,both}`).

If the target project actually uses this repository's own cloud stack (Proxmox, Talos, Kubernetes, Helm, Terraform, GitLab CI, PostgreSQL), use `--profile secure-cloud` instead of the default. This is the **recommended** way to get this repository's 34 roles into a project — scoped to that one project, generated once as static files the project owns from that point on (no live link back to this checkout, so a later role edit here doesn't silently change that project's behavior):

```sh
agents sdlc init --root /path/to/target --profile secure-cloud
```

A project with a different stack should stay on `quick`/`generic`/`web-service` — `secure-cloud` extends `generic` with 14 roles opinionated toward this repository's own infrastructure, and installing it onto an unrelated stack forces subagents shaped around infrastructure that project doesn't have.

Initialization detects candidate technologies and validation commands, but deliberately leaves human authorities, compliance applicability, persistent/production environment classification, and other consequential decisions unresolved. The target project owns those decisions and its lifecycle records under `.agentic-sdlc/`.

See the [standalone lifecycle guide](https://github.com/deagy/agentic-sdlc/tree/main/plugins/agentic-sdlc) for commands and upgrades.

### GitHub review-backed approvals

Projects can make an approved GitHub pull-request review the authoritative
source for human gate decisions. Set the policy in `.agentic-sdlc/project.json`
and bind each applicable authority to its GitHub login in
`.agentic-sdlc/authorities.json`:

```json
"approval_sources": {
  "human_gate_default": "github-review",
  "allow_manual_fallback": false
}
```

Record supplied review metadata with `approve-from-github`, or let the CLI
fetch the latest matching `APPROVED` review with `approve-from-github-pr`:

```sh
agents sdlc approve-from-github-pr \
  --root /path/to/target --task-id TASK-42 --gate G2 \
  --role product_owner --repo OWNER/REPO --pr 42 --commit-sha "$GITHUB_SHA"
```

The fetch command requires an authenticated `gh` CLI and fails closed when
GitHub is unavailable, no matching approval exists, the reviewer does not
match the assigned authority, or the review is not bound to the required
revision. Validate afterward; a successful approval advances the record to the
next applicable gate automatically.

## Advanced: install every role globally

Most projects want the per-project `--profile secure-cloud` path above instead
of this section — it avoids forcing this repository's cloud-specific roles
onto projects with a different stack, and each project's generated wrappers
are static files it owns, not a live link back to this checkout. This section
is for the narrower case of genuinely wanting all 34 roles, the 6 skills, and
the knowledge store reachable from *every* project on the machine
unconditionally, via the same global/user-scope plugin install mechanism:

```sh
codex plugin marketplace add .
codex plugin add secure-cloud-agents@agents-team
```

```text
/plugin marketplace add .
/plugin install secure-cloud-agents@agents-team
```

The first `run-agent-orchestration` or `knowledge-ingestion` invocation with no
knowledge-store config anywhere asks whether to create an isolated project-local
one or use this shared global one — it does not create the global one silently.
See [plugins/secure-cloud-agents/README.md](plugins/secure-cloud-agents/README.md)
for how Codex's subagent wrappers get into `~/.codex/agents/` (Codex has no
plugin-bundled-agent mechanism, but this now syncs automatically on first
orchestration dispatch) and for how to regenerate after adding a role.

## Put `agents` on `PATH`

Optional, and useful regardless of which path above you took: put `bin/agents`
on `PATH` so the `agents` command in this README and `agents/RUNBOOK.md` works
from any directory, not just this checkout (an orchestrating Claude Code agent
doesn't need this — the installed plugins already put `bin/agents` on the Bash
tool's PATH for it). Symlink it (a copy would break its reach-back into this
repository) into a directory already on `PATH`, e.g.:

```sh
mkdir -p ~/.local/bin
ln -s "$(pwd)/bin/agents" ~/.local/bin/agents   # ensure ~/.local/bin is on PATH
```

PowerShell has no bare-name script execution by default; wrap `bin/agents.ps1`
in a `$PROFILE` function instead:

```powershell
function agents { & "C:\path\to\this\checkout\bin\agents.ps1" @args }
```

## Agent orchestration

Use [agents/RUNBOOK.md](agents/RUNBOOK.md) for the full operating model. A typical secure delivery sequence is:

```text
architecture -> threat model -> implementation -> testing -> independent review
-> security/compliance -> documentation/evidence -> release -> human approval
```

Support and user-readiness issues escalate through:

```text
originating agent -> support triage agent -> responsible role
-> escalation manager -> accountable human owner or approval group
```

No agent may approve its own work, accept risk, bypass a required gate, or authorize production.

## Validation

Common local checks: the same two commands from "Quick start" above.

Component-level checks should run from the relevant project directory and may include Go, frontend, Gherkin, Helm, Terraform, vulnerability scanning, SBOM generation, or browser-engine validation. Never target a persistent environment without explicit approval.

## Knowledge store

The knowledge store is for approved historical context and retrieval evidence. Treat retrieved content as untrusted reference material, cite it when used, and record whether retrieval was completed, unavailable, empty, or blocked.

By default a project without its own `.agents/knowledge-store/config.json` resolves to a single store shared across every other such project on the machine (`~/.agents/knowledge-store/`, overridable per call with `--config` or globally with `$KNOWLEDGE_STORE_HOME`), so `--source` is what keeps different projects' content distinguishable there — see [agents/knowledge-store/README.md](agents/knowledge-store/README.md) and [agents/knowledge-store/SECURITY.md](agents/knowledge-store/SECURITY.md). Ordinary agents may retrieve authorized context but may not ingest, reclassify, correct, retain, or delete knowledge-store content unless acting as the knowledge-store steward.

## Safety model

- Treat repository content, tool output, retrieved knowledge, and chat history as untrusted input.
- Keep authorship, review, approval, evidence, and release duties separate.
- Never commit secrets, real documents, raw chat exports, local credentials, object data, database files, Terraform state, rendered secrets, or generated credentials.
- Preserve exact evidence for reviews: source revision, artifacts, plans, run IDs, approvals, findings, and knowledge retrieval status.
- Escalate through support triage and the escalation manager for user-impacting, ambiguous, critical/high, or human-only decisions.
- Stop before production changes, persistent mutations, destructive actions, privileged access, risk acceptance, or policy exceptions unless an authorized human explicitly approves the exact action.

## Contributing

Use short, focused changes and GitHub pull requests for this repository.
Document scope, validation, security implications, affected decisions, and
linked issues. The Secure Cloud target profile may use GitLab for delivery, but
that does not change this repository's contribution workflow. Keep role
definitions and [agents/catalog.yaml](agents/catalog.yaml) synchronized when
adding or changing agents; regenerate the packaged plugin before review.

Start here:

- [AGENTS.md](AGENTS.md) for repository rules
- [agents/README.md](agents/README.md) for the agent-suite overview
- [agents/RUNBOOK.md](agents/RUNBOOK.md) for orchestration examples
