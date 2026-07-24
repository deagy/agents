---
name: agent-authoring
description: Create or update this repository's agent definitions, catalog entries, routing rules, knowledge focus, workflows, runbook examples, and selector tests. Use when adding a specialist agent, changing agent authority, or keeping orchestration dispatch behavior consistent.
---

> Packaged suite note: when the current project has no local `agents/` tree, resolve suite files under `../../suite/agents/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.


# Agent Authoring

Use this skill when an agent change must be publishable and selectable, not just a loose Markdown file.

## Required changes

For each new or changed agent:

1. Add or update `agents/<domain>/<agent-name>/AGENT.md` with role, inputs, outputs, required checks, authority, escalation, and completion criteria.
2. Update `agents/catalog.yaml` with the exact definition path and phase.
3. Update `agents/orchestration/routing.yaml` with path/keyword rules and `knowledge_focus` text.
4. Update or add workflow/runbook examples when the role changes dispatch behavior.
5. Add selector tests in `agents/orchestration/test/test_selector.py` for at least one representative path or keyword.
6. Run `agents generate-plugin` to regenerate the self-contained `plugins/secure-cloud-agents/` package for the new or changed role, and commit the result.
7. Run the orchestration test suite and confirm catalog definition paths exist.

## Guardrails

- Do not let an implementation agent approve its own work.
- Keep human-only decisions behind explicit gates.
- Keep role authority narrow and environment-specific.
- Prefer adding a focused specialist only when existing agents would blur accountability or miss recurring work.
