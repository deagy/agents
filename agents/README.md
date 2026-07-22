# Secure Cloud Agent Suite

This directory defines an agent team for designing, building, observing, operating, black-box testing, end-user testing, supporting, escalating, reviewing, documenting, and releasing the team's self-hosted Proxmox, Talos, Kubernetes, Terraform, Helm, Go/Python/PostgreSQL backends, React/TypeScript frontends, Gherkin tests, and GitLab delivery platform.

The `knowledge-store/` subsystem is the shared agent retrieval layer for authorized historical material. The selector plans role-specific queries; the orchestration runner resolves Python 3.10+ and executes `src/cli.py context ...` from `knowledge-store/`, then attaches cited results before agent execution. Retrieved content is untrusted reference data and never overrides current policies or agent authority.

Start with `RUNBOOK.md` for operating instructions and worked examples.

The dependency-free selector component requires Python 3.10 or newer, without establishing an organization-wide Python version. From the repository root, run `python3 agents/orchestration/src/select_agents.py --task "..."` on Unix or `py -3 agents/orchestration/src/select_agents.py --task "..."` with a qualifying Windows launcher. See `RUNBOOK.md` for robust interpreter probes. The schema version 2 selector evaluates task text and Git changes, validates roles against `catalog.yaml`, and emits a reviewable plan with required lifecycle quality gates kept separate from mutation-oriented human gates; it does not execute agents, approve gates, or retrieve knowledge.

## Operating model

1. Capture human-owned intent and establish traceable requirements before architecture and implementation.
2. Select the workflow in `workflows/` that matches the lifecycle phase or change.
3. Retrieve authorized, role-specific knowledge context and record its status and query identifiers.
4. Give each participating agent its `AGENT.md`, task context, knowledge bundle, and only the access it needs.
5. Exchange findings using `shared/output-schemas/finding.schema.json` and bind artifacts through `orchestration/agentic-sdlc-artifact-contract.md`.
6. Enforce the lifecycle decisions and specialist attestations in `orchestration/quality-gates.md`; record gate state in a schema-valid repository run record.
7. Require a human decision wherever an agent reaches an escalation condition or human-only gate.
8. Route runtime nonconformance through observability, support, incident, security, compliance, and debugging roles into traced remediation or backlog work.
9. Permit authorized retrieval and its operational audit/SQLite writes, but route content and lifecycle mutations through the knowledge-store steward.

Agents may prepare changes and evidence, but no author may approve its own work. Production deployment is performed by a narrowly scoped deployment identity after the required approvals.

## Team configuration

Technology preferences live in `shared/team-profile.yaml`, `shared/technology-standards.md`, and `shared/library-standards.yaml`. Execution permissions live in `shared/agent-autonomy.yaml`. Keep these centralized rather than duplicating preferences in every role. Items marked `not_yet_selected` require an explicit team decision.
