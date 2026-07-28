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
| Set up lifecycle gates without touching a CLI | `lifecycle-onboarding` skill — ask an agent to run it |
| Work with lifecycle gates or plugins (direct CLI) | [Lifecycle and plugin operations](lifecycle-and-plugin-operations.md) |
| Find a specialist role | [Role index](role-index.md) |
| Contribute to this GitHub repository | [Contributing](../CONTRIBUTING.md) |
| Follow the complete operating model | [Runbook](../agents/RUNBOOK.md) |
| See worked-example workflows | [workflows directory](../agents/workflows/) (see `RUNBOOK.md` for which one applies to your task) |

## Source of truth

Canonical role definitions, policies, routing, workflows, and orchestration
contracts live under `agents/`. The `plugins/agents/` directory is
a self-contained distribution and may contain generated copies. Edit canonical
source files, then regenerate the package when the change requires it.

The portable lifecycle kernel is maintained separately in
[deagy/agentic-sdlc](https://github.com/deagy/agentic-sdlc). This repository
provides its Secure Cloud roles and provider profile; it does not own the
portable lifecycle state machine.
