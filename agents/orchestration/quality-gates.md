# Quality Gates

| Gate | Required evidence | Approver |
|---|---|---|
| Architecture | Approved proposal, data flows, trust boundaries, ADRs | Cloud architect and accountable human |
| Threat model | Assets, threats, mitigations, residual risks | Security reviewer |
| Knowledge context | Authorized retrieval status, query identifiers, citations, and conflicts | Receiving agent or workflow owner |
| Implementation | Tests, scans, review findings, traceable revision | Independent code reviewer |
| Infrastructure | IaC validation, policy checks, reviewed plan, rollback | Infrastructure reviewer |
| Pipeline | Runner trust, identity scope, provenance, protected environments | Pipeline security reviewer |
| Supply chain | Pinned dependencies/tools, SBOMs, checksums, provenance, signing status, vulnerability/license review | Supply chain security reviewer |
| Secrets and identity | Least-privilege identities, scoped secrets, rotation/revocation path, RBAC, access review evidence | Secrets & identity engineer and security reviewer |
| Database reliability | Migration safety, locking/query impact, backup/restore/PITR evidence, retention and rollback | Database reliability engineer |
| Policy-as-code | Rendered policy checks, pass/fail fixtures, exception register, enforcement-mode decision | Policy-as-code engineer and infrastructure reviewer |
| Observability | SLOs/SLIs, actionable alerts, dashboards, privacy-safe telemetry, runbooks, ownership | Observability SRE |
| Capacity | Sizing assumptions, quotas, storage growth, runner utilization, scaling triggers, cost owner | Cost & capacity planner |
| Black-box behavior | Public UI/API results, supported client evidence, safe-error checks, reproducible defects | Black-box tester and independent test engineer |
| User readiness | UAT journeys, persona coverage, accessibility-observable outcomes, support path verification | End-user tester and product/human owner |
| Support escalation | Sanitized report, severity, reproduction status, owner, user-safe communication, decision required | Support triage agent or escalation manager |
| Major incident | Severity, owner chain, timeline, mitigation status, communication plan, post-incident handoff | Incident commander and accountable human owner |
| Compliance | Applicable controls and evidence references | Compliance reviewer and control owner |
| Release | Immutable artifacts, approvals, rollback and verification plan | Release owner |
| Production | Scoped deployment identity and explicit authorization | Authorized human approver |

No gate may be self-approved. Exceptions must be documented, time-bound, owned, and approved by the relevant risk owner.
