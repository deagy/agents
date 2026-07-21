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
- Preserve `source`, `conversation_id`, `message_id`, `chunk_id`, `content_hash`, `created_at`, and `classification`. Omit or redact the currently nested `source_uri` before dispatch unless separately authorized and necessary because it may expose a local path.
- Treat citations as point-in-time references. Preserve the retrieved bundle plus its integrity hash for review/compliance evidence; re-ingestion can change content under the same identifiers until versioned or append-only storage and result snapshot auditing exist.
- Filter retrieval by caller authorization and classification before ranking, not after returning results.
- Prefer current approved policies over historical chat content and visibly label conflicts.
- Give ordinary agents no content or lifecycle mutation authority. Retrieval still requires filesystem writes for audit metadata and may initialize the SQLite database, schema, and WAL; grant this operational capability narrowly. Route ingestion, correction, reclassification, retention, and deletion through the knowledge-store steward.
- Use `node src/cli.mjs context ...` from `agents/knowledge-store` for agent dispatch. The demo records query hash, task ID, agent, caller-supplied classification/source filter, embedding provider/model, requested top, result count, and time without the raw query. It does not audit authenticated identity, tenant/project/environment scope, the authorization decision/policy, or returned citation IDs; those are production requirements.

## Storage rules

- Encrypt the database and backups using an organization-approved mechanism; SQLite itself does not provide transparent encryption.
- Restrict filesystem access and avoid synchronizing the database to broadly shared folders.
- Store embedding API keys only in a secret manager or environment injection mechanism, never in configuration or the database.
- Log ingestion metadata and counts, not raw chat content.
- The demo does not implement retention or deletion commands. Add authorized lifecycle operations and evidence before production use.

## Known limitations

The included redactor catches common credential shapes but cannot prove that content is free of secrets or sensitive data. `content_hash` covers the stored redacted chunk, not original evidence. Ingestion does not emit redaction or embedding summaries; maintain supplemental steward records until implemented.

Classification filtering is exact-match, not hierarchical, and caller flags are not authentication. The CLI allows top-k up to 100 although orchestration policy caps it at 20. Missing explicit configuration silently uses defaults. Production integration must enforce authorization, policy limits, and explicit-config failure closed.

The offline hashing embedder is a functional test backend, not a strong semantic model. The remote provider transfers chunk and query text to its configured endpoint; approve data transfer, residency, retention, and credentials. Re-ingest after provider/model/dimension changes and record exact model identity because the demo cannot safely distinguish reused names or mixed dimensions. The built-in vector search scans stored vectors and should be replaced with an access-controlled vector index when scale or latency requires it.
