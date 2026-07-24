<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Getting started

This guide is for someone using the suite from a checkout of this repository.
For a target project's lifecycle setup, use the [lifecycle and plugin
operations guide](lifecycle-and-plugin-operations.md).

## Prerequisites

- Python 3.10 or newer.
- A checkout of this repository.
- The standalone Agentic SDLC executable when running lifecycle-integrated
  orchestration tests or commands.

The `bin/agents` launcher probes for `python3` or `python`; PowerShell users
can use `bin/agents.ps1`.

## Five-minute path

From the repository root:

```sh
./bin/agents select \
  --task "Review a React and Go upload feature" \
  --files frontend/src/App.tsx,services/internal/api/api.go \
  --classification internal \
  --task-id EXAMPLE-1
```

The selector produces a reviewable dispatch plan. It does not execute agents,
retrieve knowledge, approve gates, deploy, mutate infrastructure, merge, or
push changes.

Run the suite-only check with:

```sh
python3 -m unittest discover -s agents/knowledge-store/test -p "test_*.py"
```

The orchestration tests use the standalone lifecycle contract. After installing
the pinned Agentic SDLC executable, run them with:

```sh
AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc \
  python3 -m unittest discover -s agents/orchestration/test -p "test_*.py"
```

See the [lifecycle guide](lifecycle-and-plugin-operations.md) for installation
and version-lock guidance.

## Choosing the next guide

- Need roles for a task? Read [Orchestration](orchestration.md).
- Need a project overlay or gate record? Read [Lifecycle and plugin operations](lifecycle-and-plugin-operations.md).
- Need a role's purpose and handoff? Read the [role index](role-index.md).
- Need a complete worked example? Read the [runbook](../agents/RUNBOOK.md),
  starting with its section index.
