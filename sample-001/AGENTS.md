# SAMPLE-001 Contributor Instructions

Treat this subtree as a local/demo implementation. Production deployment, persistent migrations, risk acceptance, and infrastructure mutation remain prohibited.

Use React with TypeScript in `apps/frontend/` and Go in `services/`. Keep browser tokens out of storage, enforce authorization only on the server, and never make quarantine or non-clean content downloadable. Preserve the public API and lifecycle contracts documented in the SAMPLE-001 design package.

Use preferred Go libraries from `../agents/shared/library-standards.yaml`. Dependencies and tool versions must be exact and reviewed. Add Gherkin scenarios for integration and regression behavior. Never commit `.env.local`, generated credentials, document fixtures containing sensitive data, database files, object-store contents, Terraform state, rendered secrets, or unpinned release artifacts.

Local validation must be non-production and disposable. Starting Podman or other local services requires explicit task authorization. Helm is render-only and Terraform is validation-only; no install, plan, apply, backend, provider, state, or resource operations belong in this slice.

When editing `deploy/compose/`, test against the intended Compose provider when available and preserve Docker/Podman compatibility notes in `deploy/README.md`. PostgreSQL 18+ named volumes mount at `/var/lib/postgresql`. Object-storage volume permission relaxations must remain local/demo-only, explicit through `SAMPLE001_ALLOW_RELAXED_STORAGE_PERMISSIONS`, and excluded from Helm or production-shaped image assumptions.
