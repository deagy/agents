# Skills catalog

This repository publishes 9 Codex-native skills under
[`.agents/skills/`](../.agents/skills/), each a self-contained `SKILL.md` plus
any supporting `references/`. Claude Code discovers the same skills through
thin per-skill pointer files under [`.claude/skills/`](../.claude/skills/)
(see `AGENTS.md`'s project-structure note); `cadre generate-plugin` also
packages them into the plugin package's `skills/`. Do not hand-edit the packaged
copy — edit the source under `.agents/skills/` and regenerate.

Name and description below are pulled verbatim from each skill's own
`SKILL.md` YAML frontmatter (`name` / `description`), which is also the exact
text a runner uses to decide when to invoke the skill.

| Skill | Description | Definition |
| --- | --- | --- |
| `agent-authoring` | Create or update this repository's agent definitions, catalog entries, routing rules, knowledge focus, workflows, runbook examples, and selector tests. Use when adding a specialist agent, changing agent authority, or keeping orchestration dispatch behavior consistent. | [SKILL.md](../.agents/skills/agent-authoring/SKILL.md) |
| `gitlab-pipeline-review` | Review GitLab CI/CD changes for secure pipeline design, runner trust, artifact integrity, SBOM/provenance, secrets exposure, and no-deploy guardrails. Use for .gitlab-ci.yml, CI templates, runner configuration, package-only pipelines, or promotion/release evidence checks. | [SKILL.md](../.agents/skills/gitlab-pipeline-review/SKILL.md) |
| `knowledge-ingestion` | Safely ingest, test, and retrieve historical chat exports for this repository's vectorized knowledge store. Use when parsing another model's chat history, adding a knowledge-store source, validating embeddings/retrieval, or preparing agent-readable context with citations. | [SKILL.md](../.agents/skills/knowledge-ingestion/SKILL.md) |
| `lifecycle-onboarding` | Conversationally set up Agentic SDLC lifecycle tracking (G1-G10 gates) for a project, for a human who does not want to touch a CLI, YAML, or JSON directly. Use when a user asks to "set up feature tracking," "onboard this project," "start tracking gates/progress," or "initialize lifecycle" for this repository or any other project. | [SKILL.md](../.agents/skills/lifecycle-onboarding/SKILL.md) |
| `lifecycle-review` | Conversationally record a human's approve/reject/request-changes decision for an Agentic SDLC lifecycle gate (G1-G10), for a human who does not want to touch a CLI or JSON directly. Use when a user asks to "approve this gate," "review G<N>," "sign off on requirements/architecture/etc," "reject this," or "request changes" for a project already onboarded with lifecycle-onboarding. | [SKILL.md](../.agents/skills/lifecycle-review/SKILL.md) |
| `local-compose-debug` | Diagnose and fix local Docker Compose or Podman Compose failures for repository demo stacks. Use for compose network label conflicts, PostgreSQL 18 volume layout errors, rootless volume permissions, frontend cache/node_modules mount problems, and local-only container startup issues. | [SKILL.md](../.agents/skills/local-compose-debug/SKILL.md) |
| `release-evidence-package` | Assemble auditable release or demo-package evidence for this repository. Use when collecting source revisions, test results, scans, SBOMs, checksums, rendered manifests, OpenTofu validation, reviews, approvals, exceptions, and unavailable-tool reports. | [SKILL.md](../.agents/skills/release-evidence-package/SKILL.md) |
| `role-discovery` | Conversationally help a new or occasional user figure out which of this repository's 70 specialist roles fit their task, and how to phrase a real `cadre select` call. Use when a user asks "which agent should I use," "who does X kind of work," "what role fits this task," or seems unsure how the role catalog or routing works. | [SKILL.md](../.agents/skills/role-discovery/SKILL.md) |
| `run-agent-orchestration` | Select, coordinate, and consolidate this repository's secure cloud agents. Use when a user asks to orchestrate, dispatch, coordinate, or run agents or subagents; execute an orchestration plan; or review a task through the repository agent suite, including software, frontend, backend, documentation, architecture, testing, code review, security, compliance, CI/CD, infrastructure, release, or knowledge-store work. | [SKILL.md](../.agents/skills/run-agent-orchestration/SKILL.md) |

## Keeping this page in sync

After adding, removing, or renaming a skill (or editing its `name`/
`description` frontmatter) under `.agents/skills/`, update the table above in
the same change, then run `cadre generate-plugin` and re-run
`python3 -m unittest agents.orchestration.test.test_repository_health` — that
test enforces catalog/plugin drift but does not check this page, so treat
divergence here as a documentation bug to fix by hand.
