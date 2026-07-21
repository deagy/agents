# SAMPLE-001 Local Vertical Slice

This directory contains a local-only secure document-upload demonstration based on the design package in `../agents/orchestration/examples/SAMPLE-001/`.

The slice uses a React/TypeScript frontend, Go BFF and internal services, PostgreSQL, protocol-faithful development fakes, Podman Compose, a render-only Helm chart, a resource-free Terraform contract, and a no-deploy GitLab pipeline.

## Safety boundary

This is not a production system. Development adapters must fail closed outside explicit development or test mode. The Helm and Terraform artifacts are review contracts, not deployment authorization. Do not use real confidential documents, persistent credentials, production identities, or shared environments.

The original production decisions DEC-001 through DEC-009 remain open. See the [local decision overlay](../agents/orchestration/examples/SAMPLE-001/local-slice-decisions.yaml) for the narrower choices authorized for this demonstration.

## Workspace

- `apps/frontend/`: Vite, React, TypeScript, and browser tests
- `services/`: Go commands, internal packages, and unit tests
- `db/migrations/`: Goose SQL migrations
- `tests/features/`: Godog/Gherkin behavior specifications
- `deploy/`: disposable Compose and render-only Helm contracts
- `infra/`: validate-only Terraform interface

Component-specific commands and prerequisites are documented in their directories. Do not initialize Podman, run migrations against persistent databases, install Helm resources, or apply Terraform without separate authorization.

## Validation status

The repository-local Go, Godog contract, Vitest, typecheck, frontend build, Python contract, and static delivery tests are executable without deployment. The migration CI job additionally runs a real HTTP fake-OIDC/BFF/API/filesystem/worker slice plus database capability-denial checks against disposable PostgreSQL. The broader Godog and browser matrices, Go race support, Podman rendering, Helm, Terraform, Kubernetes policy checks, vulnerability scans, and SBOM production require the prepared disposable GitLab runner described in the pipeline.
