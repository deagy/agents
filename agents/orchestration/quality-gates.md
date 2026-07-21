# Quality Gates

| Gate | Required evidence | Approver |
|---|---|---|
| Architecture | Approved proposal, data flows, trust boundaries, ADRs | Cloud architect and accountable human |
| Threat model | Assets, threats, mitigations, residual risks | Security reviewer |
| Knowledge context | Authorized retrieval status, query identifiers, citations, and conflicts | Receiving agent or workflow owner |
| Implementation | Tests, scans, review findings, traceable revision | Independent code reviewer |
| Infrastructure | IaC validation, policy checks, reviewed plan, rollback | Infrastructure reviewer |
| Pipeline | Runner trust, identity scope, provenance, protected environments | Pipeline security reviewer |
| Black-box behavior | Public UI/API results, supported client evidence, safe-error checks, reproducible defects | Black-box tester and independent test engineer |
| User readiness | UAT journeys, persona coverage, accessibility-observable outcomes, support path verification | End-user tester and product/human owner |
| Support escalation | Sanitized report, severity, reproduction status, owner, user-safe communication, decision required | Support triage agent or escalation manager |
| Compliance | Applicable controls and evidence references | Compliance reviewer and control owner |
| Release | Immutable artifacts, approvals, rollback and verification plan | Release owner |
| Production | Scoped deployment identity and explicit authorization | Authorized human approver |

No gate may be self-approved. Exceptions must be documented, time-bound, owned, and approved by the relevant risk owner.
