<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Role index

This index is a human-readable view of the 34 roles in
[`agents/catalog.yaml`](../agents/catalog.yaml). The catalog and each linked
`AGENT.md` remain authoritative.

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
| data-governance-engineer | design | Define classification, ownership, lineage, residency, retention, and deletion requirements. | [AGENT.md](../agents/data/data-governance-engineer/AGENT.md) |
| cryptographic-assurance-engineer | security | Assess cryptographic inventory, algorithms, keys, certificates, and agility. | [AGENT.md](../agents/security/cryptographic-assurance-engineer/AGENT.md) |
| secrets-identity-engineer | security | Review secrets, workload identity, credentials, RBAC, and access boundaries. | [AGENT.md](../agents/security/secrets-identity-engineer/AGENT.md) |
| policy-as-code-engineer | security | Design machine-enforced guardrails for infrastructure and delivery policy. | [AGENT.md](../agents/security/policy-as-code-engineer/AGENT.md) |
| database-reliability-engineer | operations | Assess PostgreSQL reliability, migrations, backups, recovery, and performance risk. | [AGENT.md](../agents/data/database-reliability-engineer/AGENT.md) |
| observability-sre | operations | Design telemetry, SLOs, alerts, dashboards, and day-2 readiness. | [AGENT.md](../agents/operations/observability-sre/AGENT.md) |

## Engineering and delivery

| Role | Phase | Purpose | Definition |
| --- | --- | --- | --- |
| application-engineer | build | Implement cross-stack application changes against approved requirements. | [AGENT.md](../agents/engineering/application-engineer/AGENT.md) |
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
| code-reviewer | review | Independently assess application correctness, security, maintainability, and tests. | [AGENT.md](../agents/review/code-reviewer/AGENT.md) |
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
