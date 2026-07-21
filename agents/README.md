# Secure Cloud Agent Suite

This directory defines an agent team for designing, building, reviewing, documenting, and releasing the team's self-hosted Proxmox, Talos, Kubernetes, Terraform, Helm, Go/Python/PostgreSQL backends, React/TypeScript frontends, Gherkin tests, and GitLab delivery platform.

The `knowledge-store/` subsystem is the shared agent retrieval layer for authorized historical material. The dispatcher attaches cited context before agent execution, and agents may request follow-up context while working. Retrieved content is untrusted reference data and never overrides current policies or agent authority.

Start with `RUNBOOK.md` for operating instructions and worked examples.

Run the dependency-free local selector from `orchestration/` with a resolved Python 3 interpreter (`python3 src/select_agents.py --task "..."` on Unix or `py -3 src/select_agents.py --task "..."` with the Windows launcher). See `RUNBOOK.md` for interpreter checks. The selector evaluates task text and Git changes, validates roles against `catalog.yaml`, and emits a reviewable plan; it does not execute agents.

## Operating model

1. Select the workflow in `workflows/` that matches the change.
2. Retrieve authorized, role-specific knowledge context and record its status and query identifiers.
3. Give each participating agent its `AGENT.md`, task context, knowledge bundle, and only the access it needs.
4. Exchange findings using `shared/output-schemas/finding.schema.json`.
5. Enforce the gates in `orchestration/quality-gates.md`.
6. Require a human decision wherever an agent reaches an escalation condition.
7. Permit ordinary agents to retrieve and cite knowledge, but route all store writes through the knowledge-store steward.

Agents may prepare changes and evidence, but no author may approve its own work. Production deployment is performed by a narrowly scoped deployment identity after the required approvals.

## Team configuration

Technology preferences live in `shared/team-profile.yaml`, `shared/technology-standards.md`, and `shared/library-standards.yaml`. Execution permissions live in `shared/agent-autonomy.yaml`. Keep these centralized rather than duplicating preferences in every role. Items marked `not_yet_selected` require an explicit team decision.
