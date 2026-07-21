# Quality Gates

| Gate | Required evidence | Approver |
|---|---|---|
| Architecture | Approved proposal, data flows, trust boundaries, ADRs | Cloud architect and accountable human |
| Threat model | Assets, threats, mitigations, residual risks | Security reviewer |
| Implementation | Tests, scans, review findings, traceable revision | Independent code reviewer |
| Infrastructure | IaC validation, policy checks, reviewed plan, rollback | Infrastructure reviewer |
| Pipeline | Runner trust, identity scope, provenance, protected environments | Pipeline security reviewer |
| Compliance | Applicable controls and evidence references | Compliance reviewer and control owner |
| Release | Immutable artifacts, approvals, rollback and verification plan | Release owner |
| Production | Scoped deployment identity and explicit authorization | Authorized human approver |

No gate may be self-approved. Exceptions must be documented, time-bound, owned, and approved by the relevant risk owner.
