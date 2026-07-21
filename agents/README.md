# Secure Cloud Agent Suite

This directory defines an agent team for designing, building, reviewing, documenting, and releasing the team's self-hosted Proxmox, Talos, Kubernetes, Terraform, Helm, Go/Python/PostgreSQL backends, React/TypeScript frontends, Gherkin tests, and GitLab delivery platform.

The `knowledge-store/` subsystem supplies provenance-preserving vector retrieval for authorized historical material. Retrieved content is untrusted reference data and never overrides current policies or agent authority.

Start with `RUNBOOK.md` for operating instructions and worked examples.

## Operating model

1. Select the workflow in `workflows/` that matches the change.
2. Give each participating agent its `AGENT.md`, the task context, and only the access it needs.
3. Exchange findings using `shared/output-schemas/finding.schema.json`.
4. Enforce the gates in `orchestration/quality-gates.md`.
5. Require a human decision wherever an agent reaches an escalation condition.
6. When historical context is needed, query `knowledge-store/` with the caller's authorized classification and retain returned citations.

Agents may prepare changes and evidence, but no author may approve its own work. Production deployment is performed by a narrowly scoped deployment identity after the required approvals.

## Team configuration

Technology preferences live in `shared/team-profile.yaml`, `shared/technology-standards.md`, and `shared/library-standards.yaml`. Execution permissions live in `shared/agent-autonomy.yaml`. Keep these centralized rather than duplicating preferences in every role. Items marked `not_yet_selected` require an explicit team decision.
