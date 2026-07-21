# Repository Guidelines

## Project Structure & Module Organization

Agent roles, policies, workflows, orchestration, and the knowledge store live under `agents/`; publishable skills live under `.agents/skills/`. The local SAMPLE-001 product demonstration is isolated under `sample-001/`: React code is in `apps/frontend/`, Go commands and packages in `services/`, migrations in `db/`, Gherkin in `tests/features/`, and delivery contracts in `deploy/` and `infra/`.

Read `agents/RUNBOOK.md` for orchestration and `sample-001/AGENTS.md` before product changes. Keep role definitions and `agents/catalog.yaml` synchronized.

## Build, Test, and Development Commands

Resolve Python 3.10+ as documented in the runbook. From each internal-tool component, run:

```powershell
<python> -B -m unittest discover -s test -p "test_*.py"
```

From `sample-001/services/`, use `go test ./...`, `go test -race ./...`, and `go vet ./...`. From `sample-001/apps/frontend/`, use `npm ci`, `npm test`, `npm run typecheck`, and `npm run build`. Podman, PostgreSQL migrations, Helm, and Terraform remain disposable or validation-only; follow the component README and never target a persistent environment without approval.

## Coding Style & Naming Conventions

Use four-space indentation and snake_case for Python. Format Go with `gofmt`; keep packages lowercase and errors safe for callers. Use two spaces, strict TypeScript, semantic React markup, CSS Modules, and lowercase kebab-case directories. Prefer the Go libraries in `agents/shared/library-standards.yaml`; pin and justify every added dependency.

## Testing Guidelines

Use `unittest` for internal Python tools, Go `testing` plus Testify for services, and Vitest/Testing Library for React. Express integration and regression behavior in Gherkin/Godog. Cover authorization, negative paths, state transitions, accessibility, failure recovery, migrations, and sensitive-data exclusion. Use synthetic fixtures only.

## Commit & Merge Request Guidelines

Use short imperative commit subjects and focused changes. GitLab merge requests must describe scope, security implications, validation, affected decisions, and linked issues. Include CLI or UI evidence when behavior changes.

Never commit secrets, raw chat exports, real documents, local environment files, databases, object data, generated credentials, Terraform state, or rendered secrets. Preserve independent review and human gates for persistent mutations, production, risk acceptance, and release.
