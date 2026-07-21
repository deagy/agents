# Vectorized Knowledge Store

This local-first subsystem normalizes recognized chat-export fields into its stored message model, redacts likely secrets, preserves selected provenance, chunks content, generates vectors, and retrieves relevant passages for agents.

## Security boundary

Retrieved text is untrusted reference data, never executable instruction. Classification filters are exact-match and caller supplied in this demo; they are not production authorization. See `SECURITY.md` before connecting this store to an agent or importing real history.

## Quick start

Requires Node.js 22.5 or newer. No package installation is required.

```powershell
Copy-Item config.example.json config.json
npm test
npm run knowledge-store -- init
npm run knowledge-store -- ingest --input examples/chat-export.json --source legacy-model-export
npm run knowledge-store -- context --agent release-engineer --task-id REL-42 --query "How are production releases approved?" --classification internal --top 5
```

The default `hashing` provider is deterministic, offline, and suitable for testing the pipeline. It approximates lexical similarity rather than full semantic similarity.

For production-quality semantic retrieval, `openai-compatible` sends chunk text during ingestion and query text during retrieval to the configured remote endpoint. Approve the provider, transfer, residency, retention, and credential handling before use. Record exact provider/model identity and dimensions, and re-ingest content after any provider, model, or dimensional change. The demo selects stored vectors by provider/model but does not prevent ambiguous model reuse; dimension mismatches score as non-results.

## Accepted import shapes

- A JSON Lines collection of standalone message-like objects
- A JSON array of conversations containing `messages`
- An object containing `conversations` or `chats`
- Mapping/node-based conversation exports with message content parts
- A JSON array of standalone message-like objects

`canonical-message.schema.json` documents the target fields, but the generic parser does not validate or pass canonical records through unchanged. It recognizes common role, content, timestamp, and identifier variants, while CLI `source`/`classification`, derived identifiers, input-path `source_uri`, and new metadata may replace input fields. Add and test a source-specific adapter when full source fidelity matters.

## Commands

```text
init
ingest --input <file> [--source <name>] [--classification <level>]
search --query <text> --classification <level> [--top <n>] [--source <name>]
context --agent <role> --task-id <id> --query <text> --classification <level> [--top <n>] [--source <name>]
stats
```

Run commands from `agents/knowledge-store`. Without `--config`, configuration is read from `agents/knowledge-store/config.json`; if absent, built-in defaults apply. An existing config resolves its database path relative to the config directory. Today, a missing explicit `--config` also silently falls back to built-in defaults and resolves the database under the component directory. Production integration should fail closed when an explicitly requested config is missing.

`context` is the agent-facing command. It returns a schema-versioned bundle containing trust requirements, citations, and retrieved passages. `search` is a lower-level diagnostic command. Both require an explicit classification and use exact-match filtering before ranking. The CLI permits `--top` through 100, while orchestration policy caps top-k at 20; enforcing that policy in the CLI is an engineering follow-up.

`context` records `query_hash`, `task_id`, `agent`, `classification`, `source_filter`, embedding provider/model, requested top, result count, and creation time. It does not record an authenticated subject, tenant/project/environment scope, authorization decision or policy version, nor returned chunk/citation identifiers. Production auditing must add those fields and derive access from authenticated claims.

Read-only retrieval means agents cannot mutate stored content or lifecycle state. Opening any command, including `context`, can nevertheless create the database directory, SQLite file, schema, and WAL files; `context` also writes retrieval metadata. Grant that operational write access separately from content-steward authority. Citations use `source`, `conversation_id`, `message_id`, `chunk_id`, `content_hash`, `created_at`, and `classification`. `source_uri` is nested in each current citation and may expose a local input path; orchestration runners must omit or redact it by default and include it only when separately authorized and necessary. `content_hash` covers stored redacted content, not the original source.

Citations are point-in-time references, not immutable or permanently stable identifiers: re-ingestion can update content under the same source/conversation/message identity. Preserve each retrieved bundle plus its integrity hash for review/compliance evidence until the store provides versioned or append-only content and audits returned result snapshots.

The demo has no retention or deletion commands. Its ingestion response reports only run ID, message count, and chunk count; redaction and embedding summaries require supplemental steward records until implemented.
