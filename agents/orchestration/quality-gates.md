# Quality Gates

The lifecycle uses two tiers. Progression gates G1-G10 decide whether work may
advance. Specialist gates provide bounded attestations consumed by one or more
progression gates. An attestation is evidence, not permission to advance,
release, mutate a persistent environment, or accept risk.

Knowledge context is a cross-cutting prerequisite, not a lifecycle progression
gate. Every phase records an authorized retrieval status, including unavailable,
empty, unauthorized, or not-applicable, and preserves citations and conflicts.

## Universal gate record

Every progression and specialist gate record must contain:

- Gate identifier, tier, applicability (`applicable`, `not-applicable`, or
  `unknown`), status, and decision timestamp.
- Exact source revision, artifact identifiers and digests, target environment,
  and deployment/configuration identity when relevant.
- Preparer, independent verifier, and human approver identities or an explicit
  explanation when a verifier or human approver is not required.
- Gate-specific verifier role and explicit applicability for conditional
  authorities. G4 records data/control-owner applicability; G5 records human
  key-owner applicability; G6 records Product Owner UAT applicability; and G10
  records whether Security and Governance Leads are implicated. `unknown`
  authority applicability blocks approval.
- Evidence references with integrity hashes and the knowledge-retrieval status.
- Findings and their dispositions.
- Exceptions with justification, compensating controls, accountable human
  owner, approver, expiry, and remediation plan.
- Invalidation history and the earliest required re-entry gate.

No gate may be self-approved. A verifier who materially corrects an artifact
becomes an author and cannot approve that revision. The run record must declare
that the verifier is not the preparer and made no material correction; identity
comparison also requires semantic validation because JSON Schema cannot compare
values in separate fields.

An applicable gate cannot be approved while required evidence is absent, an
applicable SQS item or required specialized BOM has `unknown` applicability or
undefined semantics, an exception is expired or incomplete, or a blocking
finding is unresolved. `not-applicable` requires a rationale and accountable
owner. Agents may prepare or attest; only the stated decision authority may
approve progression.

## Lifecycle progression gates

| ID | Gate | Required evidence and pass criteria | Decision authority | Failure and re-entry route |
|---|---|---|---|---|
| G1 | Intent | Versioned intent with owner, human-set priority, users and outcomes, scope, exclusions, classification, constraints, environments, measurable success criteria, and owners for every conflict. | Human Product Owner | Return to the Product Intent Agent. Priority, scope, cancellation, and mission interpretation remain human-only. |
| G2 | Requirements Baseline | Approved intent; stable requirement IDs; acceptance criteria; dependencies; non-functional requirements; control, test, and evidence obligations; downstream gate applicability; complete bidirectional traceability. | Human Product Owner and Engineering Lead | Return to the Requirements Agent; objective conflicts re-enter G1. |
| G3 | Architecture | Requirements-linked architecture, boundaries, APIs, data and trust flows, ADRs, failure/recovery behavior, technology choices, validation obligations, and resolved applicable SQS profile items. | Human System Architect. The Cloud Architect may attest completeness but cannot approve its own design. | Return to the architecture author; requirement conflicts re-enter G2. |
| G4 | Governance and Data | Control mappings, jurisdictions, accreditation relevance, data inventory and lineage, residency, non-egress, retention/deletion, derived outputs, enforcement, and evidence obligations. | Independent Compliance Reviewer plus human Governance Lead and applicable data/control owner. | Return to requirements, architecture, data, or policy owner. Unknown applicable SQS semantics block approval. |
| G5 | Security and Crypto | Threat model, identity/secrets design, dependency posture, crypto inventory, algorithms, key lifecycle, certificates, agility, downgrade analysis, mitigations, tests, and residual risks. | Independent Security Reviewer plus human Security Lead and human key owner where applicable. | Return to architecture or implementation. Critical/high findings block unless an authorized human owns a complete, unexpired exception. |
| G6 | Verification and Test | Exact revision; requirement-linked unit, integration, regression, security, performance, recovery, policy, black-box, and UAT evidence as applicable; scan results, defect dispositions, and independence declaration. | Independent Test Engineer and human Engineering Lead; Human Product Owner for UAT. | Return to the owning implementer. Unmet acceptance criteria require human disposition and may re-enter G2. |
| G7 | Evidence | Immutable evidence index containing revisions, digests, provenance, reviews, tests, ADRs, exceptions, documentation, retention/classification, and every applicable formally defined BOM. | Independent Compliance Reviewer and accountable human Release Owner. | Return to the evidence producer or the gate that produced defective evidence. Undefined required BOM semantics block approval. |
| G8 | Release Readiness | G1-G7 approvals, immutable artifact, target compatibility, deployment/migration plan, rollback, SLOs, alerts, runbooks, capacity, support ownership, stop thresholds, and change window. | Accountable human Release Owner. | Return to the relevant readiness owner and earliest affected gate. |
| G9 | Deployment Authorization | Exact artifact, environment, deployment identity, plan, window, blast radius, rollback, and verification thresholds explicitly approved without substitution. | Authorized Human Release Authority only. | Deny or return to G8 on mismatch, expiry, substitution, or stale approval. |
| G10 | Runtime Conformance | Deployed version/config identity, observation window, SLO/business/security/data/trust/governance signals, drift, incidents, findings, owners, and traced backlog updates. | Human Service Owner; Security or Governance Leads when their domains are implicated. | Roll back, invoke incident response, remediate, or return to G1, G2, or G6 according to change materiality. |

## Specialist attestation gates

These 19 existing controls remain independently reviewable attestations.

| Attestation | Required evidence | Attestor | Consumed by |
|---|---|---|---|
| Architecture | Approved proposal, data flows, trust boundaries, ADRs | Cloud Architect and independent accountable architect | G3 |
| Threat model | Assets, threats, mitigations, residual risks | Security Reviewer | G5 |
| Knowledge context | Authorized retrieval status, query identifiers, citations, and conflicts | Receiving agent or workflow owner | Cross-cutting prerequisite |
| Implementation | Tests, scans, review findings, traceable revision | Independent Code Reviewer | G6 |
| Infrastructure | IaC validation, policy checks, reviewed plan, rollback | Infrastructure Reviewer | G6, G8 |
| Pipeline | Runner trust, identity scope, provenance, protected environments | Pipeline Security Reviewer | G5, G6, G8 |
| Supply chain | Pinned dependencies/tools, SBOMs, checksums, provenance, signing status, vulnerability/license review | Supply Chain Security Reviewer | G5, G7, G8 |
| Secrets and identity | Least-privilege identities, scoped secrets, rotation/revocation path, RBAC, access review evidence | Secrets & Identity Engineer and independent Security Reviewer | G5 |
| Database reliability | Migration safety, locking/query impact, backup/restore/PITR evidence, retention and rollback | Database Reliability Engineer | G4, G6, G8 |
| Policy-as-code | Rendered policy checks, pass/fail fixtures, exception register, enforcement-mode decision | Policy-as-Code Engineer and Infrastructure Reviewer | G4, G6 |
| Observability | SLOs/SLIs, actionable alerts, dashboards, privacy-safe telemetry, runbooks, ownership | Observability SRE | G8, G10 |
| Capacity | Sizing assumptions, quotas, storage growth, runner utilization, scaling triggers, cost owner | Cost & Capacity Planner | G8, G10 |
| Black-box behavior | Public UI/API results, supported client evidence, safe-error checks, reproducible defects | Black-Box Tester and independent Test Engineer | G6 |
| User readiness | UAT journeys, persona coverage, accessibility-observable outcomes, support path verification | End-User Tester and Human Product Owner | G6, G8 |
| Support escalation | Sanitized report, severity, reproduction status, owner, user-safe communication, decision required | Support Triage Agent or Escalation Manager | Event-driven; G10 when release-related |
| Major incident | Severity, owner chain, timeline, mitigation status, communication plan, post-incident handoff | Incident Commander and accountable human owner | Event-driven; G10 |
| Compliance | Applicable controls and evidence references | Compliance Reviewer and control owner | G4, G7 |
| Release | Immutable artifacts, approvals, rollback and verification plan | Release Owner | G8 |
| Production | Scoped deployment identity and explicit authorization | Authorized Human Release Authority | G9 |

## Invalidation and re-entry

A material change invalidates the earliest affected progression gate and every
dependent downstream gate. Examples: changed objectives re-enter G1; changed
acceptance criteria or controls re-enter G2; changed architecture or trust/data
flows re-enter G3; implementation-only changes re-enter G6. Runtime findings
must be traced to G1 for a mission/scope change, G2 for a requirement/control
change, or G6 for a conforming implementation fix. An invalidated record remains
immutable history; a new decision supersedes it rather than overwriting it.
