# Technology Standards

These standards specialize `team-profile.yaml`. Where a value remains `not_yet_selected`, agents must present alternatives or request a decision rather than silently choosing an organization-wide standard.

## Proxmox and Terraform

- Treat Terraform as the desired-state source for Proxmox infrastructure and supporting resources within its managed scope.
- Keep reusable modules versioned and separate cluster-wide primitives from workload-specific resources.
- Do not make undocumented console changes, edit Terraform state manually, or import/adopt resources without explicit approval and a recovery plan.
- Bind plans to an exact source revision, state snapshot, workspace, variables, provider versions, and Proxmox target.
- Highlight VM replacement, disk/storage changes, network changes, node placement, privilege changes, and lifecycle exceptions.

## Talos and Kubernetes

- Treat Talos as an immutable, API-managed operating system. Do not propose SSH-based administration, package installation on nodes, or unmanaged host changes.
- Manage Talos machine and cluster configuration declaratively, protect machine secrets and trust material, and plan quorum-safe upgrades and recovery.
- Keep Kubernetes resources declarative, namespace-scoped where practical, and least-privileged through service accounts and RBAC.
- Require resource requests/limits, health probes, disruption considerations, network policy, security context, observability, backup, and recovery appropriate to workload risk.

## Helm

- Use Helm for Kubernetes package deployment. Keep charts and values reviewable, deterministic, and environment differences explicit.
- Pin chart and image versions; avoid mutable tags for releasable workloads.
- Render and validate manifests before deployment. Review hooks, custom resources, cluster-scoped objects, RBAC, secrets references, and deletion/rollback behavior.
- Do not store secret values in chart values or rendered artifacts.

## Go and Python

- Prefer Go for services, operators, CLIs, and long-lived automation.
- Use Python when it materially simplifies a bounded task, integration, data transformation, or test utility; document why it is preferable for that component.
- Pin dependencies, use supported project-defined versions, run formatting/static analysis/tests, and avoid introducing a second implementation path without need.
- Keep interfaces and operational behavior consistent across languages.

## Gherkin testing

- Express integration and regression behavior in Gherkin using business- or operator-visible outcomes.
- Keep scenarios deterministic, independent, tagged by capability/risk, and traceable to requirements or defects.
- Avoid coupling feature text to UI selectors, internal function names, or incidental implementation details.
- Include negative, authorization, failure, recovery, upgrade, rollback, and tenant/isolation scenarios when applicable.
- Treat skipped, quarantined, or flaky scenarios as explicit findings with owners and expiry dates.

## GitLab VCS and CI/CD

- Deliver changes through GitLab merge requests against protected branches.
- Use GitLab CI/CD with least-privilege job tokens, protected variables/environments, isolated runner trust tiers, and short-lived infrastructure credentials.
- Prevent untrusted merge-request pipelines from accessing protected variables, privileged runners, or deployment identities.
- Pin included pipeline definitions, container images, and third-party tooling to reviewed immutable versions.
- Build once and promote the same immutable artifact through environments. Preserve pipeline, job, artifact, approval, and deployment evidence.
