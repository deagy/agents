---
name: sample-001-run
description: Operate the sample-001 secure document-upload vertical slice locally. Use when starting, validating, debugging, testing, or cleaning the sample-001 disposable React, Go, PostgreSQL, fake OIDC, fake scanner, Compose, Helm-render, or Terraform-validate demo.
---

# SAMPLE-001 Local Run

Use this skill for the local/demo package only. It does not authorize production deployment, persistent migrations, registry pushes, Terraform apply, Helm install, or risk acceptance.

## Preparation

1. Read `sample-001/AGENTS.md`, `sample-001/README.md`, and `sample-001/deploy/README.md`.
2. Confirm the container provider, generated environment file, loopback binding, and disposable data directories.
3. Run repository-provided validation commands before inventing alternatives.

## Run sequence

1. Generate or refresh local-only environment/configuration using the project script documented in `sample-001`.
2. Start with the provider-specific compose command from `sample-001/deploy/compose`.
3. Check PostgreSQL readiness, fake OIDC discovery/JWKS, BFF/API health, worker readiness, and frontend dev server.
4. Exercise login, upload, scan, clean download, rejected/EICAR behavior, deletion, and logout using Gherkin or documented smoke tests.
5. For failures, use `$local-compose-debug` patterns and inspect exact service logs.

## Reporting

Return commands run, service health, failing logs, generated artifacts, unavailable validations, and whether any change affects only local/demo behavior.
