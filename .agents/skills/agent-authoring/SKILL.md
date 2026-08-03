---
name: agent-authoring
description: Create or update this repository's agent definitions, catalog entries, routing rules, knowledge focus, workflows, runbook examples, and selector tests. Use when adding a specialist agent, changing agent authority, or keeping orchestration dispatch behavior consistent.
---

# Agent Authoring

Use this skill when an agent change must be publishable and selectable, not just a loose Markdown file.

## Required changes

For each new or changed agent:

1. Add or update `roster/<domain>/<agent-name>/AGENT.md` with role, inputs, outputs, required checks, authority, escalation, and completion criteria.
2. Add its id to `roster/catalog-order.txt` (dispatch-precedence order), if not already present.
3. Metadata (`phase`, `capability`, `model`, `codex_model`, `reasoning_effort`, `knowledge_focus`) lives in the `---`-delimited frontmatter at the top of the role's `AGENT.md` (see "Frontmatter-based roles" below): update the frontmatter, then run `cadre generate-role-metadata` to regenerate `roster/catalog.yaml` and routing.yaml's `knowledge_focus` block. Do not hand-edit those generated regions -- `roster/catalog.yaml` and `roster/orchestration/routing.yaml`'s `knowledge_focus` block are fully generated output, never an input. Note: `roster/catalog.yaml`'s regenerated key order always exactly tracks `roster/catalog-order.txt`, but `routing.yaml`'s `knowledge_focus` block does not -- it never reorders an already-present role and always appends a newly-added role's entry at the very end, so don't expect a new role's `knowledge_focus` entry to land near related roles there.
4. Update or add workflow/runbook examples when the role changes dispatch behavior.
5. Add selector tests in `roster/orchestration/test/test_selector.py` for at least one representative path or keyword.
6. Regenerate the packaged plugin for the new or changed role in a checkout of [`deagy/cadre-plugin`](https://github.com/deagy/cadre-plugin) (`cadre generate-plugin --output /path/to/cadre-plugin`) and commit the result there. That repository's CI re-runs the same command with `--check` against the register revision pinned in its `cadre-ref.txt`, so the two only advance together, on a deliberate bump.
7. Run the orchestration test suite and confirm catalog definition paths exist.

### Frontmatter-based roles

Every role's `AGENT.md` starts with a `---`-delimited frontmatter block declaring `id`, `phase`, `capability`, `model`, `codex_model`, `reasoning_effort`, and `knowledge_focus` as flat scalar fields (see `roster/orchestration/src/role_metadata.py`). `definition` is never stored in frontmatter -- it is always derived from the file's own path under `roster/`. A role's metadata comes entirely from its frontmatter; there is no fallback to a legacy `catalog.yaml`/`routing.yaml` entry, so a missing required field fails the generator closed rather than silently inheriting a stale value. An `AGENT.md` that does not carry frontmatter is a generator error, not a supported transitional state. Regenerate with `cadre generate-role-metadata` (`roster/orchestration/src/generate_role_metadata.py`) after editing frontmatter, and validate with `cadre generate-role-metadata --check`.

## Guardrails

- Do not let an implementation agent approve its own work.
- Keep human-only decisions behind explicit gates.
- Keep role authority narrow and environment-specific.
- Prefer adding a focused specialist only when existing agents would blur accountability or miss recurring work.
