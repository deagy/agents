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
- For black-box, UAT, or support cases: user-visible steps, expected and actual behavior, affected persona or reporter class, client/browser version, timestamps, request IDs, sanitized attachments, workaround status, and user-safe communication draft when applicable.

The receiving agent verifies completeness and rejects an ambiguous or unauditable handoff. A rejected handoff returns to its author without being treated as approval.
