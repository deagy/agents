---
name: local-compose-debug
description: Diagnose and fix local Docker Compose or Podman Compose failures for repository demo stacks. Use for compose network label conflicts, PostgreSQL 18 volume layout errors, rootless volume permissions, frontend cache/node_modules mount problems, and local-only container startup issues.
---

> Packaged suite note: when the current project has no local `agents/` tree, resolve suite files under `../../suite/agents/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.


# Local Compose Debug

Use this skill for disposable local stacks only. Do not apply production infrastructure, mutate shared clusters, or delete broad resources.

## Workflow

1. Identify the compose provider and project: `docker compose version` or `podman compose version`, compose file path, project name, and current directory.
2. Read the stack docs and compose file before editing, especially the project-local delivery README and Compose file for the stack being debugged.
3. Inspect logs and resolved config with provider-native commands. Prefer exact service logs over broad output.
4. Match common failures:
   - Network label conflict: remove or rename only the exact stale project network after confirming labels and project name.
   - PostgreSQL 18 image error: mount the volume at `/var/lib/postgresql`, not `/var/lib/postgresql/data`.
   - Rootless object volume permissions: avoid chmod/chown on provider-managed mounts; use service-owned paths or relaxed local-only permissions explicitly.
   - Vite cache error: ensure writable `node_modules`/Vite temp/cache paths are available inside the container.
5. Keep fixes environment-scoped and absent from production-shaped Helm/Terraform contracts.
6. Re-run the smallest useful startup/health check and record any unavailable tooling.

## Safety

Before removing networks, volumes, or containers, resolve exact names and labels. Do not prune globally. Preserve user data unless the stack is explicitly disposable and the target is exact.
