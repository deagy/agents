# Role index

This index is a human-readable view of the 70 roles in
[`agents/catalog.yaml`](../agents/catalog.yaml). The catalog and each linked
`AGENT.md` remain authoritative.

Sections below group roles by lifecycle `phase` (the catalog field), which
does not always match a role's `AGENT.md` directory — directories group by
subject-matter domain instead. `cost-capacity-planner` is the clearest case:
`phase: planning` (it estimates demand before commitments are made) but its
definition lives under `agents/operations/` (capacity and cost are an
operations concern once a workload is live). Treat `catalog.yaml`'s `phase`
as authoritative for sequencing; the directory is only a filing convenience.
For a phase/capability-tier browsable view instead, see the
[capability index](capability-index.md); for term definitions (capability
tier, route, quality gate, human gate, ...), see the
[glossary](terminology.md).

## Planning and governance

| Role | Phase | Purpose | Definition |
| --- | --- | --- | --- |
| product-intent-agent | planning | Translate a human mission into a reviewable intent record. | [AGENT.md](../agents/planning/product-intent-agent/AGENT.md) |
| requirements-agent | planning | Decompose approved intent into testable, traceable obligations. | [AGENT.md](../agents/planning/requirements-agent/AGENT.md) |
| governance-planner | design | Plan governance, policy, control, jurisdiction, and evidence obligations. | [AGENT.md](../agents/governance/governance-planner/AGENT.md) |
| cost-capacity-planner | planning | Estimate capacity, resource demand, storage, utilization, and cost tradeoffs. | [AGENT.md](../agents/operations/cost-capacity-planner/AGENT.md) |

## Architecture, security, and data

| Role | Phase | Purpose | Definition |
| --- | --- | --- | --- |
| cloud-architect | design | Design secure, resilient, operable, cost-aware architecture. | [AGENT.md](../agents/architecture/cloud-architect/AGENT.md) |
| threat-modeler | design | Identify credible threats and translate them into testable requirements. | [AGENT.md](../agents/architecture/threat-modeler/AGENT.md) |
| api-contract-engineer | design | Own cross-service API/schema contract design, versioning, and compatibility. | [AGENT.md](../agents/architecture/api-contract-engineer/AGENT.md) |
| interaction-designer | design | Own user-facing interaction/UX design, flow states, and accessibility intent upstream of implementation. | [AGENT.md](../agents/architecture/interaction-designer/AGENT.md) |
| data-governance-engineer | design | Define classification, ownership, lineage, residency, retention, and deletion requirements. | [AGENT.md](../agents/data/data-governance-engineer/AGENT.md) |
| cryptographic-assurance-engineer | security | Assess cryptographic inventory, algorithms, keys, certificates, and agility. | [AGENT.md](../agents/security/cryptographic-assurance-engineer/AGENT.md) |
| secrets-identity-engineer | security | Review secrets, workload identity, credentials, RBAC, and access boundaries. | [AGENT.md](../agents/security/secrets-identity-engineer/AGENT.md) |
| policy-as-code-engineer | security | Design machine-enforced guardrails for infrastructure and delivery policy. | [AGENT.md](../agents/security/policy-as-code-engineer/AGENT.md) |
| database-reliability-engineer | operations | Assess PostgreSQL reliability, migrations, backups, recovery, and performance risk. | [AGENT.md](../agents/data/database-reliability-engineer/AGENT.md) |
| observability-sre | operations | Design telemetry, SLOs, alerts, dashboards, and day-2 readiness. | [AGENT.md](../agents/operations/observability-sre/AGENT.md) |
| finops-engineer | operations | Monitor live cost/utilization drift against the approved capacity model. | [AGENT.md](../agents/operations/finops-engineer/AGENT.md) |
| decommission-engineer | operations | Plan and verify preconditions for retiring a capability or service after G10. | [AGENT.md](../agents/operations/decommission-engineer/AGENT.md) |

## Engineering and delivery

| Role | Phase | Purpose | Definition |
| --- | --- | --- | --- |
| application-engineer | build | Own routine changes to this suite's own tooling, catalog, and orchestration source (not a target project's application code). | [AGENT.md](../agents/engineering/application-engineer/AGENT.md) |
| frontend-engineer | build | Build secure, accessible React and TypeScript frontends. | [AGENT.md](../agents/engineering/frontend-engineer/AGENT.md) |
| backend-engineer | build | Build secure Go backend services with PostgreSQL. | [AGENT.md](../agents/engineering/backend-engineer/AGENT.md) |
| infrastructure-provisioner | build | Create reusable infrastructure-as-code and reviewable plans. | [AGENT.md](../agents/engineering/infrastructure-provisioner/AGENT.md) |
| cicd-engineer | build | Build secure pipelines for tests, scans, artifacts, promotion, and rollback. | [AGENT.md](../agents/engineering/cicd-engineer/AGENT.md) |
| debugging-engineer | build | Reproduce failures, identify root cause, and apply scoped authorized fixes. | [AGENT.md](../agents/engineering/debugging-engineer/AGENT.md) |
| release-engineer | release | Coordinate artifact promotion and release execution after required gates. | [AGENT.md](../agents/engineering/release-engineer/AGENT.md) |

## Verification and review

| Role | Phase | Purpose | Definition |
| --- | --- | --- | --- |
| test-engineer | verify | Design and execute risk-based application, infrastructure, pipeline, and resilience tests. | [AGENT.md](../agents/engineering/test-engineer/AGENT.md) |
| black-box-tester | verify | Validate external behavior without implementation or privileged shortcuts. | [AGENT.md](../agents/testing/black-box-tester/AGENT.md) |
| end-user-tester | verify | Evaluate whether users can safely complete intended workflows. | [AGENT.md](../agents/testing/end-user-tester/AGENT.md) |
| performance-testing-engineer | verify | Validate throughput, latency, and capacity assumptions against a candidate build. | [AGENT.md](../agents/testing/performance-testing-engineer/AGENT.md) |
| chaos-resilience-engineer | verify | Inject controlled faults in disposable environments to verify RTO/RPO and alerting claims. | [AGENT.md](../agents/testing/chaos-resilience-engineer/AGENT.md) |
| code-reviewer | review | Independently assess application correctness, security, maintainability, and tests. | [AGENT.md](../agents/review/code-reviewer/AGENT.md) |
| accessibility-reviewer | review | Independently verify browser-facing changes against the accessibility target. | [AGENT.md](../agents/review/accessibility-reviewer/AGENT.md) |
| infrastructure-reviewer | review | Independently assess infrastructure security, correctness, resilience, and impact. | [AGENT.md](../agents/review/infrastructure-reviewer/AGENT.md) |
| pipeline-security-reviewer | review | Independently review CI/CD trust boundaries, identities, runners, artifacts, and deployment controls. | [AGENT.md](../agents/review/pipeline-security-reviewer/AGENT.md) |
| supply-chain-security-reviewer | review | Review dependency, build, package, SBOM, provenance, signing, and image risks. | [AGENT.md](../agents/review/supply-chain-security-reviewer/AGENT.md) |
| security-reviewer | review | Evaluate the end-to-end change against threats, policy, guardrails, and risk tolerance. | [AGENT.md](../agents/review/security-reviewer/AGENT.md) |
| compliance-reviewer | review | Assess applicable controls and durable audit-ready evidence. | [AGENT.md](../agents/review/compliance-reviewer/AGENT.md) |

## Documentation, support, and knowledge

| Role | Phase | Purpose | Definition |
| --- | --- | --- | --- |
| technical-writer | document | Create accurate, task-oriented documentation from approved sources. | [AGENT.md](../agents/documentation/technical-writer/AGENT.md) |
| evidence-curator | evidence | Collect, normalize, index, protect, and retain delivery and compliance evidence. | [AGENT.md](../agents/documentation/evidence-curator/AGENT.md) |
| knowledge-store-steward | knowledge | Operate the authorized, provenance-preserving agent knowledge store. | [AGENT.md](../agents/knowledge-store/AGENT.md) |
| support-triage-agent | support | Classify user reports, protect sensitive data, and route actionable cases. | [AGENT.md](../agents/support/support-triage-agent/AGENT.md) |
| escalation-manager | support | Coordinate escalations so urgent or high-risk issues stop at the right gate. | [AGENT.md](../agents/support/escalation-manager/AGENT.md) |
| incident-commander | support | Coordinate major incidents while preserving safety, evidence, and communication. | [AGENT.md](../agents/support/incident-commander/AGENT.md) |

## Governance, authority, and challenge functions

Cross-cutting roles that gate, route, capture provenance for, or deliberately challenge other work, rather than producing it. Distinct from the human authority aides below, which prepare a decision package for one named human lifecycle authority; these roles instead produce a finding, register entry, or determination usable at any applicable gate.

| Role | Phase | Purpose | Definition |
| --- | --- | --- | --- |
| halt-authority | review | Hold the cross-cutting stop-control finding: arrest work in progress on a doctrine, architecture, evidence-chain, or safety condition. | [AGENT.md](../agents/review/halt-authority/AGENT.md) |
| approval-router | review | Encode the authority matrix and block work until the required signature is present. | [AGENT.md](../agents/governance/approval-router/AGENT.md) |
| doctrine-conformance | review | Verify narrative, framing, and terminology against the project's doctrine and terminology register. | [AGENT.md](../agents/review/doctrine-conformance/AGENT.md) |
| architecture-authority | review | Enforce the abstraction-layer rule; reject any change reaching infrastructure without an approved boundary. | [AGENT.md](../agents/review/architecture-authority/AGENT.md) |
| scope-boundary | planning | Reject work that drifts outside the stated build boundary into future-state capability. | [AGENT.md](../agents/planning/scope-boundary/AGENT.md) |
| phase-gate | release | Verify a build phase's exit criteria are met and evidenced before the next phase begins. | [AGENT.md](../agents/review/phase-gate/AGENT.md) |
| assumption-register | planning | Track what the build depends on being true and what observation would invalidate it. | [AGENT.md](../agents/planning/assumption-register/AGENT.md) |
| decision-record | document | Capture decision provenance: who decided, when, on what basis, and what alternatives were rejected. | [AGENT.md](../agents/documentation/decision-record/AGENT.md) |
| red-team | verify | Run adversarial assessment against the system as actually deployed, not as designed. | [AGENT.md](../agents/testing/red-team/AGENT.md) |
| premortem | planning | Assume a committed initiative already failed and work backward to plausible causes. | [AGENT.md](../agents/planning/premortem/AGENT.md) |
| first-principles-challenger | design | Challenge whether an inherited design constraint is real or just unexamined. | [AGENT.md](../agents/architecture/first-principles-challenger/AGENT.md) |
| subtraction-agent | review | Argue for removal on any scope increase, feature addition, or interface expansion. | [AGENT.md](../agents/review/subtraction-agent/AGENT.md) |
| falsification-agent | verify | Demand the disproving test for any claim of correctness, resilience, or continuity. | [AGENT.md](../agents/testing/falsification-agent/AGENT.md) |
| deployment-realist | operations | Assess operability at real scale with real participants, not demonstrated feasibility. | [AGENT.md](../agents/operations/deployment-realist/AGENT.md) |
| classification-and-marking-gate | release | Determine whether an artifact is correctly classified and marked, and may leave the environment. | [AGENT.md](../agents/review/classification-and-marking-gate/AGENT.md) |
| claim-conformance | release | Verify an external-facing artifact does not assert more than the project can demonstrate. | [AGENT.md](../agents/review/claim-conformance/AGENT.md) |
| vendor-register-steward | operations | Maintain the vendor/tooling register and detect drift as repositories and workflows change. | [AGENT.md](../agents/operations/vendor-register-steward/AGENT.md) |
| retention-and-deletion-executor | operations | Execute already-approved retention and deletion obligations, with evidence. | [AGENT.md](../agents/operations/retention-and-deletion-executor/AGENT.md) |
| agent-performance-evaluator | operations | Assess whether the roles in this catalog are producing correct output. | [AGENT.md](../agents/operations/agent-performance-evaluator/AGENT.md) |
| agent-version-control | operations | Maintain provenance for the agent definitions themselves as they change. | [AGENT.md](../agents/operations/agent-version-control/AGENT.md) |
| ip-provenance-agent | evidence | Apply the current IP rule version to an artifact's provenance record and produce a determination. | [AGENT.md](../agents/documentation/ip-provenance-agent/AGENT.md) |

## Human authority aides

Read-only agents that prepare the decision package a named human lifecycle
authority needs for their assigned gate(s) — never approve, recommend a
disposition, or hold delegated authority themselves. See
[`docs/proposals/human-authority-role-agents.md`](proposals/human-authority-role-agents.md)
for the design rationale, including why they never state a recommended
disposition and why delegated approval authority was deliberately not built
here.

| Role | Phase | Purpose | Definition |
| --- | --- | --- | --- |
| product-owner-aide | authority | Prepare G1/G2/G6 decision packages for the human Product Owner. | [AGENT.md](../agents/authority/product-owner-aide/AGENT.md) |
| engineering-lead-aide | authority | Prepare G2/G6 decision packages for the human Engineering Lead. | [AGENT.md](../agents/authority/engineering-lead-aide/AGENT.md) |
| system-architect-aide | authority | Prepare G3 decision packages for the human System Architect. | [AGENT.md](../agents/authority/system-architect-aide/AGENT.md) |
| governance-lead-aide | authority | Prepare G4 decision packages for the human Governance Lead. | [AGENT.md](../agents/authority/governance-lead-aide/AGENT.md) |
| security-lead-aide | authority | Prepare G5 decision packages for the human Security Lead. | [AGENT.md](../agents/authority/security-lead-aide/AGENT.md) |
| release-owner-aide | authority | Prepare G7/G8 decision packages for the human Release Owner. | [AGENT.md](../agents/authority/release-owner-aide/AGENT.md) |
| release-authority-aide | authority | Prepare G9 decision packages for the human Release Authority. | [AGENT.md](../agents/authority/release-authority-aide/AGENT.md) |
| service-owner-aide | authority | Prepare G10 decision packages for the human Service Owner. | [AGENT.md](../agents/authority/service-owner-aide/AGENT.md) |
