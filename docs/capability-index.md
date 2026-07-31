# Capability index

This page lists all 70 roles from [`agents/catalog.yaml`](../agents/catalog.yaml)
grouped by their `capability` and `phase` fields, so you can find every role
in a given class of change authority (for example, every role that can only
review, or every role that can operate a live environment) or every role
active in a given lifecycle stage. `agents/catalog.yaml` remains the
authoritative source; this is a generated-by-hand snapshot of it, not a live
filter — regenerate it after any `catalog.yaml` change (see "Keeping this
page in sync" below).

For a purpose-oriented view grouped by subject-matter domain instead, see the
[role index](role-index.md). See the [glossary](terminology.md) for the
"capability tier" definition and other recurring terms.

## By capability

`capability` is each role's `agents/catalog.yaml` field. It describes the
class of change authority a role has, not its subject-matter domain --
see each role's own `AGENT.md` "Authority" section for its exact scope.

### `read_only` (28 roles)

Reads and evaluates only; produces findings, decision packages, or approvals but does not edit the artifact it assesses.

| Role | Phase | Definition |
| --- | --- | --- |
| accessibility-reviewer | review | [AGENT.md](../agents/review/accessibility-reviewer/AGENT.md) |
| agent-performance-evaluator | operations | [AGENT.md](../agents/operations/agent-performance-evaluator/AGENT.md) |
| approval-router | review | [AGENT.md](../agents/governance/approval-router/AGENT.md) |
| architecture-authority | review | [AGENT.md](../agents/review/architecture-authority/AGENT.md) |
| claim-conformance | release | [AGENT.md](../agents/review/claim-conformance/AGENT.md) |
| classification-and-marking-gate | release | [AGENT.md](../agents/review/classification-and-marking-gate/AGENT.md) |
| code-reviewer | review | [AGENT.md](../agents/review/code-reviewer/AGENT.md) |
| compliance-reviewer | review | [AGENT.md](../agents/review/compliance-reviewer/AGENT.md) |
| deployment-realist | operations | [AGENT.md](../agents/operations/deployment-realist/AGENT.md) |
| doctrine-conformance | review | [AGENT.md](../agents/review/doctrine-conformance/AGENT.md) |
| engineering-lead-aide | authority | [AGENT.md](../agents/authority/engineering-lead-aide/AGENT.md) |
| falsification-agent | verify | [AGENT.md](../agents/testing/falsification-agent/AGENT.md) |
| first-principles-challenger | design | [AGENT.md](../agents/architecture/first-principles-challenger/AGENT.md) |
| governance-lead-aide | authority | [AGENT.md](../agents/authority/governance-lead-aide/AGENT.md) |
| halt-authority | review | [AGENT.md](../agents/review/halt-authority/AGENT.md) |
| infrastructure-reviewer | review | [AGENT.md](../agents/review/infrastructure-reviewer/AGENT.md) |
| phase-gate | release | [AGENT.md](../agents/review/phase-gate/AGENT.md) |
| pipeline-security-reviewer | review | [AGENT.md](../agents/review/pipeline-security-reviewer/AGENT.md) |
| product-owner-aide | authority | [AGENT.md](../agents/authority/product-owner-aide/AGENT.md) |
| release-authority-aide | authority | [AGENT.md](../agents/authority/release-authority-aide/AGENT.md) |
| release-owner-aide | authority | [AGENT.md](../agents/authority/release-owner-aide/AGENT.md) |
| scope-boundary | planning | [AGENT.md](../agents/planning/scope-boundary/AGENT.md) |
| security-lead-aide | authority | [AGENT.md](../agents/authority/security-lead-aide/AGENT.md) |
| security-reviewer | review | [AGENT.md](../agents/review/security-reviewer/AGENT.md) |
| service-owner-aide | authority | [AGENT.md](../agents/authority/service-owner-aide/AGENT.md) |
| subtraction-agent | review | [AGENT.md](../agents/review/subtraction-agent/AGENT.md) |
| supply-chain-security-reviewer | review | [AGENT.md](../agents/review/supply-chain-security-reviewer/AGENT.md) |
| system-architect-aide | authority | [AGENT.md](../agents/authority/system-architect-aide/AGENT.md) |

### `document_author` (20 roles)

Creates or edits documents, plans, and requirements (not application code).

| Role | Phase | Definition |
| --- | --- | --- |
| agent-version-control | operations | [AGENT.md](../agents/operations/agent-version-control/AGENT.md) |
| api-contract-engineer | design | [AGENT.md](../agents/architecture/api-contract-engineer/AGENT.md) |
| assumption-register | planning | [AGENT.md](../agents/planning/assumption-register/AGENT.md) |
| cloud-architect | design | [AGENT.md](../agents/architecture/cloud-architect/AGENT.md) |
| cost-capacity-planner | planning | [AGENT.md](../agents/operations/cost-capacity-planner/AGENT.md) |
| cryptographic-assurance-engineer | security | [AGENT.md](../agents/security/cryptographic-assurance-engineer/AGENT.md) |
| data-governance-engineer | design | [AGENT.md](../agents/data/data-governance-engineer/AGENT.md) |
| decision-record | document | [AGENT.md](../agents/documentation/decision-record/AGENT.md) |
| escalation-manager | support | [AGENT.md](../agents/support/escalation-manager/AGENT.md) |
| evidence-curator | evidence | [AGENT.md](../agents/documentation/evidence-curator/AGENT.md) |
| governance-planner | design | [AGENT.md](../agents/governance/governance-planner/AGENT.md) |
| interaction-designer | design | [AGENT.md](../agents/architecture/interaction-designer/AGENT.md) |
| ip-provenance-agent | evidence | [AGENT.md](../agents/documentation/ip-provenance-agent/AGENT.md) |
| premortem | planning | [AGENT.md](../agents/planning/premortem/AGENT.md) |
| product-intent-agent | planning | [AGENT.md](../agents/planning/product-intent-agent/AGENT.md) |
| requirements-agent | planning | [AGENT.md](../agents/planning/requirements-agent/AGENT.md) |
| support-triage-agent | support | [AGENT.md](../agents/support/support-triage-agent/AGENT.md) |
| technical-writer | document | [AGENT.md](../agents/documentation/technical-writer/AGENT.md) |
| threat-modeler | design | [AGENT.md](../agents/architecture/threat-modeler/AGENT.md) |
| vendor-register-steward | operations | [AGENT.md](../agents/operations/vendor-register-steward/AGENT.md) |

### `code_author` (9 roles)

Creates or edits application, infrastructure, pipeline, or policy-as-code source.

| Role | Phase | Definition |
| --- | --- | --- |
| application-engineer | build | [AGENT.md](../agents/engineering/application-engineer/AGENT.md) |
| backend-engineer | build | [AGENT.md](../agents/engineering/backend-engineer/AGENT.md) |
| cicd-engineer | build | [AGENT.md](../agents/engineering/cicd-engineer/AGENT.md) |
| database-reliability-engineer | operations | [AGENT.md](../agents/data/database-reliability-engineer/AGENT.md) |
| debugging-engineer | build | [AGENT.md](../agents/engineering/debugging-engineer/AGENT.md) |
| frontend-engineer | build | [AGENT.md](../agents/engineering/frontend-engineer/AGENT.md) |
| infrastructure-provisioner | build | [AGENT.md](../agents/engineering/infrastructure-provisioner/AGENT.md) |
| policy-as-code-engineer | security | [AGENT.md](../agents/security/policy-as-code-engineer/AGENT.md) |
| secrets-identity-engineer | security | [AGENT.md](../agents/security/secrets-identity-engineer/AGENT.md) |

### `test_author` (5 roles)

Creates or edits test artifacts and executes them against authorized non-production environments.

| Role | Phase | Definition |
| --- | --- | --- |
| black-box-tester | verify | [AGENT.md](../agents/testing/black-box-tester/AGENT.md) |
| end-user-tester | verify | [AGENT.md](../agents/testing/end-user-tester/AGENT.md) |
| performance-testing-engineer | verify | [AGENT.md](../agents/testing/performance-testing-engineer/AGENT.md) |
| red-team | verify | [AGENT.md](../agents/testing/red-team/AGENT.md) |
| test-engineer | verify | [AGENT.md](../agents/engineering/test-engineer/AGENT.md) |

### `environment_operator` (8 roles)

Operates authorized environments directly (observability, release, incident response, chaos, knowledge-store, cost/finops).

| Role | Phase | Definition |
| --- | --- | --- |
| chaos-resilience-engineer | verify | [AGENT.md](../agents/testing/chaos-resilience-engineer/AGENT.md) |
| decommission-engineer | operations | [AGENT.md](../agents/operations/decommission-engineer/AGENT.md) |
| finops-engineer | operations | [AGENT.md](../agents/operations/finops-engineer/AGENT.md) |
| incident-commander | support | [AGENT.md](../agents/support/incident-commander/AGENT.md) |
| knowledge-store-steward | knowledge | [AGENT.md](../agents/knowledge-store/AGENT.md) |
| observability-sre | operations | [AGENT.md](../agents/operations/observability-sre/AGENT.md) |
| release-engineer | release | [AGENT.md](../agents/engineering/release-engineer/AGENT.md) |
| retention-and-deletion-executor | operations | [AGENT.md](../agents/operations/retention-and-deletion-executor/AGENT.md) |

## By phase

`phase` is each role's `agents/catalog.yaml` field, used for lifecycle
sequencing. It does not always match the role's `AGENT.md` directory --
see the [role index](role-index.md) for the subject-matter-domain
grouping instead.

### `planning` (6 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| assumption-register | document_author | [AGENT.md](../agents/planning/assumption-register/AGENT.md) |
| cost-capacity-planner | document_author | [AGENT.md](../agents/operations/cost-capacity-planner/AGENT.md) |
| premortem | document_author | [AGENT.md](../agents/planning/premortem/AGENT.md) |
| product-intent-agent | document_author | [AGENT.md](../agents/planning/product-intent-agent/AGENT.md) |
| requirements-agent | document_author | [AGENT.md](../agents/planning/requirements-agent/AGENT.md) |
| scope-boundary | read_only | [AGENT.md](../agents/planning/scope-boundary/AGENT.md) |

### `design` (7 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| api-contract-engineer | document_author | [AGENT.md](../agents/architecture/api-contract-engineer/AGENT.md) |
| cloud-architect | document_author | [AGENT.md](../agents/architecture/cloud-architect/AGENT.md) |
| data-governance-engineer | document_author | [AGENT.md](../agents/data/data-governance-engineer/AGENT.md) |
| first-principles-challenger | read_only | [AGENT.md](../agents/architecture/first-principles-challenger/AGENT.md) |
| governance-planner | document_author | [AGENT.md](../agents/governance/governance-planner/AGENT.md) |
| interaction-designer | document_author | [AGENT.md](../agents/architecture/interaction-designer/AGENT.md) |
| threat-modeler | document_author | [AGENT.md](../agents/architecture/threat-modeler/AGENT.md) |

### `security` (3 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| cryptographic-assurance-engineer | document_author | [AGENT.md](../agents/security/cryptographic-assurance-engineer/AGENT.md) |
| policy-as-code-engineer | code_author | [AGENT.md](../agents/security/policy-as-code-engineer/AGENT.md) |
| secrets-identity-engineer | code_author | [AGENT.md](../agents/security/secrets-identity-engineer/AGENT.md) |

### `build` (6 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| application-engineer | code_author | [AGENT.md](../agents/engineering/application-engineer/AGENT.md) |
| backend-engineer | code_author | [AGENT.md](../agents/engineering/backend-engineer/AGENT.md) |
| cicd-engineer | code_author | [AGENT.md](../agents/engineering/cicd-engineer/AGENT.md) |
| debugging-engineer | code_author | [AGENT.md](../agents/engineering/debugging-engineer/AGENT.md) |
| frontend-engineer | code_author | [AGENT.md](../agents/engineering/frontend-engineer/AGENT.md) |
| infrastructure-provisioner | code_author | [AGENT.md](../agents/engineering/infrastructure-provisioner/AGENT.md) |

### `verify` (7 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| black-box-tester | test_author | [AGENT.md](../agents/testing/black-box-tester/AGENT.md) |
| chaos-resilience-engineer | environment_operator | [AGENT.md](../agents/testing/chaos-resilience-engineer/AGENT.md) |
| end-user-tester | test_author | [AGENT.md](../agents/testing/end-user-tester/AGENT.md) |
| falsification-agent | read_only | [AGENT.md](../agents/testing/falsification-agent/AGENT.md) |
| performance-testing-engineer | test_author | [AGENT.md](../agents/testing/performance-testing-engineer/AGENT.md) |
| red-team | test_author | [AGENT.md](../agents/testing/red-team/AGENT.md) |
| test-engineer | test_author | [AGENT.md](../agents/engineering/test-engineer/AGENT.md) |

### `review` (12 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| accessibility-reviewer | read_only | [AGENT.md](../agents/review/accessibility-reviewer/AGENT.md) |
| approval-router | read_only | [AGENT.md](../agents/governance/approval-router/AGENT.md) |
| architecture-authority | read_only | [AGENT.md](../agents/review/architecture-authority/AGENT.md) |
| code-reviewer | read_only | [AGENT.md](../agents/review/code-reviewer/AGENT.md) |
| compliance-reviewer | read_only | [AGENT.md](../agents/review/compliance-reviewer/AGENT.md) |
| doctrine-conformance | read_only | [AGENT.md](../agents/review/doctrine-conformance/AGENT.md) |
| halt-authority | read_only | [AGENT.md](../agents/review/halt-authority/AGENT.md) |
| infrastructure-reviewer | read_only | [AGENT.md](../agents/review/infrastructure-reviewer/AGENT.md) |
| pipeline-security-reviewer | read_only | [AGENT.md](../agents/review/pipeline-security-reviewer/AGENT.md) |
| security-reviewer | read_only | [AGENT.md](../agents/review/security-reviewer/AGENT.md) |
| subtraction-agent | read_only | [AGENT.md](../agents/review/subtraction-agent/AGENT.md) |
| supply-chain-security-reviewer | read_only | [AGENT.md](../agents/review/supply-chain-security-reviewer/AGENT.md) |

### `release` (4 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| claim-conformance | read_only | [AGENT.md](../agents/review/claim-conformance/AGENT.md) |
| classification-and-marking-gate | read_only | [AGENT.md](../agents/review/classification-and-marking-gate/AGENT.md) |
| phase-gate | read_only | [AGENT.md](../agents/review/phase-gate/AGENT.md) |
| release-engineer | environment_operator | [AGENT.md](../agents/engineering/release-engineer/AGENT.md) |

### `support` (3 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| escalation-manager | document_author | [AGENT.md](../agents/support/escalation-manager/AGENT.md) |
| incident-commander | environment_operator | [AGENT.md](../agents/support/incident-commander/AGENT.md) |
| support-triage-agent | document_author | [AGENT.md](../agents/support/support-triage-agent/AGENT.md) |

### `operations` (9 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| agent-performance-evaluator | read_only | [AGENT.md](../agents/operations/agent-performance-evaluator/AGENT.md) |
| agent-version-control | document_author | [AGENT.md](../agents/operations/agent-version-control/AGENT.md) |
| database-reliability-engineer | code_author | [AGENT.md](../agents/data/database-reliability-engineer/AGENT.md) |
| decommission-engineer | environment_operator | [AGENT.md](../agents/operations/decommission-engineer/AGENT.md) |
| deployment-realist | read_only | [AGENT.md](../agents/operations/deployment-realist/AGENT.md) |
| finops-engineer | environment_operator | [AGENT.md](../agents/operations/finops-engineer/AGENT.md) |
| observability-sre | environment_operator | [AGENT.md](../agents/operations/observability-sre/AGENT.md) |
| retention-and-deletion-executor | environment_operator | [AGENT.md](../agents/operations/retention-and-deletion-executor/AGENT.md) |
| vendor-register-steward | document_author | [AGENT.md](../agents/operations/vendor-register-steward/AGENT.md) |

### `document` (2 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| decision-record | document_author | [AGENT.md](../agents/documentation/decision-record/AGENT.md) |
| technical-writer | document_author | [AGENT.md](../agents/documentation/technical-writer/AGENT.md) |

### `evidence` (2 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| evidence-curator | document_author | [AGENT.md](../agents/documentation/evidence-curator/AGENT.md) |
| ip-provenance-agent | document_author | [AGENT.md](../agents/documentation/ip-provenance-agent/AGENT.md) |

### `knowledge` (1 role)

| Role | Capability | Definition |
| --- | --- | --- |
| knowledge-store-steward | environment_operator | [AGENT.md](../agents/knowledge-store/AGENT.md) |

### `authority` (8 roles)

| Role | Capability | Definition |
| --- | --- | --- |
| engineering-lead-aide | read_only | [AGENT.md](../agents/authority/engineering-lead-aide/AGENT.md) |
| governance-lead-aide | read_only | [AGENT.md](../agents/authority/governance-lead-aide/AGENT.md) |
| product-owner-aide | read_only | [AGENT.md](../agents/authority/product-owner-aide/AGENT.md) |
| release-authority-aide | read_only | [AGENT.md](../agents/authority/release-authority-aide/AGENT.md) |
| release-owner-aide | read_only | [AGENT.md](../agents/authority/release-owner-aide/AGENT.md) |
| security-lead-aide | read_only | [AGENT.md](../agents/authority/security-lead-aide/AGENT.md) |
| service-owner-aide | read_only | [AGENT.md](../agents/authority/service-owner-aide/AGENT.md) |
| system-architect-aide | read_only | [AGENT.md](../agents/authority/system-architect-aide/AGENT.md) |

## Keeping this page in sync

This page is a snapshot, not generated tooling output. After adding, removing,
or reclassifying a role in `agents/catalog.yaml` (its `capability` or `phase`
field, or the role set itself), update the corresponding table(s) above in
the same change. `python3 -m unittest agents.orchestration.test.test_repository_health`
checks catalog/plugin drift but does not check this page against the catalog;
treat divergence here as a documentation bug to fix by hand.
