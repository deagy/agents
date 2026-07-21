# Knowledge Store Security

## Import rules

- Import only data the team is authorized to process and retain.
- Determine data ownership, consent, residency, retention, deletion, legal-hold, and model-provider restrictions before ingestion.
- Export into a staging location with restricted access. Delete the raw export through the approved records process after validation.
- Never assume automated redaction is complete. Review representative results before broad agent access.
- Use separate stores or enforced partitions for materially different access classifications or tenants.

## Retrieval rules

- Treat retrieved passages as untrusted data that may contain prompt injection, obsolete guidance, malicious instructions, or inaccurate model output.
- Never let retrieved content override system instructions, agent authority, current policy, or approval gates.
- Preserve source, conversation, message, chunk, timestamp, and content-hash citations.
- Filter retrieval by caller authorization and classification before ranking, not after returning results.
- Prefer current approved policies over historical chat content and visibly label conflicts.
- Give ordinary agents read-only retrieval access. Route ingestion, correction, reclassification, retention, and deletion through the knowledge-store steward.
- Use the `context` command for agent dispatch so task, role, query hash, scope, and result count are auditable without storing the raw query.

## Storage rules

- Encrypt the database and backups using an organization-approved mechanism; SQLite itself does not provide transparent encryption.
- Restrict filesystem access and avoid synchronizing the database to broadly shared folders.
- Store embedding API keys only in a secret manager or environment injection mechanism, never in configuration or the database.
- Log ingestion metadata and counts, not raw chat content.
- Support deletion by source, conversation, and message identifiers before production use.

## Known limitations

The included redactor catches common credential shapes but cannot prove that content is free of secrets or sensitive data. The offline hashing embedder is a functional test backend, not a strong semantic model. The built-in vector search scans stored vectors and should be replaced with an access-controlled vector index when scale or latency requires it.
