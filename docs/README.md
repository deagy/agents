# Documentation guide

Owner: Secure Cloud Agents maintainers
Status: active
Reviewed: 2026-07-24
Source of truth: repository implementation, policies, catalog, and generated manifests

Use this index to choose the shortest useful path.

| Goal | Start here |
| --- | --- |
| Understand the suite | [Identity](../IDENTITY.md), then [Terminology](terminology.md) |
| Make a first local selection | [Getting started](getting-started.md) |
| Select and coordinate roles | [Orchestration guide](orchestration.md) |
| Work with lifecycle gates or plugins | [Lifecycle and plugin operations](lifecycle-and-plugin-operations.md) |
| Find a specialist role | [Role index](role-index.md) |
| Contribute to this GitHub repository | [Contributing](../CONTRIBUTING.md) |
| Follow the complete operating model | [Runbook](../agents/RUNBOOK.md) |

## Source of truth

Canonical role definitions, policies, routing, workflows, and orchestration
contracts live under `agents/`. The `plugins/secure-cloud-agents/` directory is
a self-contained distribution and may contain generated copies. Edit canonical
source files, then regenerate the package when the change requires it.

The portable lifecycle kernel is maintained separately in
[deagy/agentic-sdlc](https://github.com/deagy/agentic-sdlc). This repository
provides its Secure Cloud roles and provider profile; it does not own the
portable lifecycle state machine.
