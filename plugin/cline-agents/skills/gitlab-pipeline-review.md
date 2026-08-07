---
name: gitlab-pipeline-review
description: Review GitLab CI/CD changes for secure pipeline design, runner trust, artifact integrity, SBOM/provenance, secrets exposure, and no-deploy guardrails. Use for .gitlab-ci.yml, CI templates, runner configuration, package-only pipelines, or promotion/release evidence checks.
canonicalSource: skills/gitlab-pipeline-review/SKILL.md
---

> Cline packaging note: this skill's instructions describe this repository's own `roster/`-layout tooling in the abstract (the role catalog, routing configuration, and selector this plugin bundles) -- they are not literal paths to look up in an arbitrary target project. When dispatching, use `start_subagent`/`dispatch_selected_roles`/`bin/cadre select` rather than reading these files directly.


# GitLab Pipeline Review

Use this skill for review or bounded repository edits to GitLab CI/CD artifacts. It does not authorize deploy jobs, registry pushes, OpenTofu plan/apply, Helm install, production environments, or secret creation.

## Review steps

1. Read `.gitlab-ci.yml`, included CI templates, this project's technology-standards documentation, and relevant workflow docs.
2. Identify all stages, jobs, images, services, variables, caches, artifacts, rules, dependencies, and protected-environment assumptions.
3. Verify untrusted merge requests and forks cannot read secrets, mint credentials, modify deployment targets, poison caches, or package unreviewed artifacts.
4. Check images/tools are pinned, runners are appropriate for trust level, artifacts have checksums/SBOMs when required, and failures are fail-closed.
5. Confirm package-only/demo pipelines contain no deploy, environment, migration-apply, registry-push, signing, promotion, OpenTofu-plan/apply, or Helm-install behavior unless explicitly approved.
6. Route findings to `pipeline-security-reviewer`, `supply-chain-security-reviewer`, and `release-engineer` when applicable.

## Output

Return an execution graph summary, trust boundaries, evidence reviewed, findings by severity, unavailable validations, and the exact next safe action.
