<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Handoff Contracts

Every handoff includes:

- Task identifier, scope, owner, and target environment.
- Exact source revision and immutable artifact identifiers.
- Inputs examined and outputs produced.
- Assumptions, exclusions, and unresolved questions.
- Structured findings with evidence and severity.
- Knowledge retrieval status, query identifiers, citations used, and stale/conflicting material.
- Required approvals and their status.
- Recommended next agent and explicit acceptance criteria.
- Intent record and requirements-baseline identifiers when supplied by the
  target project's lifecycle record.
- Trace links from requirements to architecture, controls, implementation,
  tests, findings, and evidence using the target project's lifecycle contract.
- SQS impact-profile reference when applicable, including every `unknown`
  applicability or undefined-semantics blocker.
- For black-box, UAT, or support cases: user-visible steps, expected and actual behavior, affected persona or reporter class, client/browser version, timestamps, request IDs, sanitized attachments, workaround status, and user-safe communication draft when applicable.

The receiving agent verifies completeness and rejects an ambiguous or unauditable handoff. A rejected handoff returns to its author without being treated as approval.

Material changes must be reported to the target project's lifecycle kernel for
impact analysis and any required gate invalidation. A receiving reviewer who
makes a material correction becomes an author and cannot approve that revision;
another independent reviewer must decide it.
