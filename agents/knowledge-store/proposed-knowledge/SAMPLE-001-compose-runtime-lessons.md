# Proposed Knowledge: Compose Runtime Lessons

Status: proposed for knowledge-store-steward review
Classification: internal
Source task: local compose troubleshooting on 2026-07-21

## Summary

Local startup troubleshooting exposed three reusable lessons for agents working on disposable Docker/Podman Compose stacks:

- Compose project resources can survive failed runs. A stale project network without the expected `com.docker.compose.network` label can cause Compose to refuse reuse. Cleanup must target only project-labeled disposable containers/networks.
- PostgreSQL 18 Docker images expect the persistent mount at `/var/lib/postgresql`, not `/var/lib/postgresql/data`. Old local volumes with the prior layout should be removed only when confirmed disposable.
- Docker Desktop and rootless Podman named volumes may reject `chown`/`chmod` on mounted volume roots. Local demo stacks should avoid assuming ownership changes on volume roots, document any local-only relaxed-permission flag, and keep production-shaped images and Helm contracts non-root.
- Vite 8 development servers using bundled TypeScript config loading may try to write `.vite-temp` under `node_modules`. In read-only local containers, use a config-loader mode and cache directory that write to tmpfs, such as `--configLoader runner` with `VITE_CACHE_DIR=/tmp/vite-cache`.

## Recommended Retrieval Use

Retrieve this note for backend, infrastructure, test, code-review, and documentation agents when work touches local Compose files, PostgreSQL container storage, named volumes, or local runtime troubleshooting.

## Steward Notes

Do not ingest until the steward verifies scope, classification, and whether this should be represented as operational knowledge, a decision overlay, or both.
