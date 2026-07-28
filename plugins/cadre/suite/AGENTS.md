<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Repository Guidelines

## Project Structure & Module Organization

Agent roles, policies, workflows, orchestration, testing, support/escalation, and the knowledge store live under `agents/`; publishable repository skills live under `.agents/skills/`, with thin per-skill pointer files under `.claude/skills/` (Claude Code). A single general pointer file under `.clinerules/` (Cline CLI) references `AGENTS.md`/`agents/RUNBOOK.md` directly — it is unrelated to the per-skill pointer mechanism. `plugins/cadre/` packages this suite and its Agentic SDLC provider as a self-contained distribution generated from `agents/catalog.yaml`, `agents/`, and `.agents/skills/`. `plugins/cline/` is a separate, hand-authored TypeScript source tree (not generated) implementing an installable Cline CLI plugin. The portable lifecycle kernel is maintained separately at `github.com/deagy/agentic-sdlc`.

Read `agents/RUNBOOK.md` for orchestration and any project-local `AGENTS.md` before product changes. Keep role definitions and `agents/catalog.yaml` synchronized.

## Build, Test, and Development Commands

Resolve Python 3.10+ as documented in the runbook. From each internal-tool component, run:

```powershell
<python> -B -m unittest discover -s test -p "test_*.py"
```

After changing `agents/catalog.yaml`, `agents/`, or `.agents/skills/`, regenerate `plugins/cadre/` with `cadre generate-plugin` and re-run `agents/orchestration/test/test_repository_health.py`, which fails on drift. Run lifecycle integration tests against the pinned standalone Agentic SDLC executable.

For Go services, use `gofmt`, `go tool goimports`, `go vet ./...`, `go test ./...`, `go test -race ./...`, and `go tool golangci-lint run ./...`. For React frontends, use the project-pinned package manager for install, test, typecheck, and build commands. Podman, PostgreSQL migrations, Helm, and OpenTofu remain disposable or validation-only unless a project has explicit production approval; follow the component README and never target a persistent environment without approval.

For this repository's own `plugins/cline/` source (not a target/sample project — this repo's first tracked Node/TypeScript code), run `cd plugins/cline && npm ci && npm run typecheck && npm test`.

## Coding Style & Naming Conventions

Use four-space indentation and snake_case for Python. Format Go with `gofmt` and `goimports`; lint with the committed `golangci-lint` config. Keep Go packages lowercase and errors safe for callers. Use two spaces, strict TypeScript, semantic React markup, CSS Modules, and lowercase kebab-case directories. Prefer the Go libraries and tools in `agents/shared/library-standards.yaml`; pin and justify every added dependency.

## Testing Guidelines

Use `unittest` for internal Python tools, Go `testing` plus Testify for services, and Vitest/Testing Library for React. Express integration and regression behavior in Gherkin/Godog. Cover authorization, negative paths, state transitions, accessibility, failure recovery, migrations, and sensitive-data exclusion. Use synthetic fixtures only.

## Commit & Merge Request Guidelines

Use short imperative commit subjects and focused changes. This GitHub-hosted
repository uses GitHub pull requests and GitHub Actions; each pull request must
describe scope, security implications, validation, affected decisions, and
linked issues. The Secure Cloud target profile may use GitLab merge requests
for downstream projects, but that is not this repository's contribution
workflow. Include CLI or UI evidence when behavior changes.

Never commit secrets, raw chat exports, real documents, local environment files, databases, object data, generated credentials, OpenTofu/Terraform state, or rendered secrets. Preserve independent review and human gates for persistent mutations, production, risk acceptance, and release.

## Agentic SDLC boundary

This repository is a provider/plugin distribution — it supplies provider
resources and dispatch inputs to *other* consuming projects, which own their
own `.agentic-sdlc/` overlays, run records, gate approvals, and lifecycle
decisions. This repository does not run its own `.agentic-sdlc/` overlay.

Do not copy lifecycle schemas, run-record validators, gate authorities, or
kernel authority into this repository. Never infer gate approval,
production/destructive authority, risk acceptance, or compliance applicability
for another project. Artifact authors must remain separate from independent
reviewers and human approvers.
