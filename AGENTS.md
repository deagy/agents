# Repository Guidelines

## Project Structure & Module Organization

The repository is centered on `agents/`. Role definitions live in category folders such as `agents/engineering/`, `agents/review/`, and `agents/architecture/`; each role uses an `AGENT.md`. Shared policy is under `agents/shared/`, orchestration contracts under `agents/orchestration/`, and executable procedures under `agents/workflows/`. Start with `agents/RUNBOOK.md` and keep `agents/catalog.yaml` synchronized when adding or renaming roles.

The vector knowledge store is in `agents/knowledge-store/`. Runtime modules are in `src/*.mjs`, tests in `test/*.test.mjs`, examples in `examples/`, and local databases in the ignored `data/` directory.

## Build, Test, and Development Commands

Run knowledge-store commands from `agents/knowledge-store/`:

```powershell
npm test
npm run knowledge-store -- init
npm run knowledge-store -- ingest --input examples/chat-export.json --source example --classification internal
npm run knowledge-store -- search --query "release approval" --classification internal
```

`npm test` runs the Node test suite. The other commands initialize, populate, and query a local store. Node.js 22.5 or newer is required; there is currently no separate build step or third-party install requirement.

## Coding Style & Naming Conventions

Use two-space indentation for JavaScript, TypeScript, JSON, and YAML. Knowledge-store JavaScript is ESM with `.mjs`, single quotes, semicolons, and camelCase identifiers. Product frontends prefer React with TypeScript; backends prefer Go with PostgreSQL and use Python only when necessary. Use lowercase kebab-case directories, uppercase `AGENT.md` for roles, and descriptive Markdown headings. Keep standards centralized and validate edited schemas.

## Testing Guidelines

Use `node:test` and `node:assert/strict` for the store; name tests `*.test.mjs`. Integration and regression behavior uses Gherkin. Tests must use temporary data and avoid live credentials or services. No numeric coverage threshold is defined; add regression coverage for every fixed defect.

## Commit & Merge Request Guidelines

History is small but uses short, imperative subjects, for example `Document preferred libraries and dependency policies`. Keep commits focused. GitLab merge requests should explain scope, affected agents or policies, security implications, validation performed, and linked issues when applicable. Include sample output for CLI behavior changes. Never commit secrets, raw chat exports, configuration credentials, or SQLite databases.

## Agent and Security Requirements

Before changing behavior, read `agents/shared/team-profile.yaml`, `technology-standards.md`, `library-standards.yaml`, and `agent-autonomy.yaml`. Preserve separation of authorship and approval. Persistent environment mutations, destructive actions, risk acceptance, and production releases require authorized human approval.
