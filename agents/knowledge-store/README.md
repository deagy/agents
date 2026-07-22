# Vectorized Knowledge Store

This local-first subsystem normalizes recognized chat-export fields into its stored message model, redacts likely secrets, preserves selected provenance, chunks content, generates vectors, and retrieves relevant passages for agents.

## Global by default, project-local overrides

Without an explicit `--config`, the CLI resolves configuration in this order:

1. **Project-local**: walk up from the current directory looking for
   `.agents/knowledge-store/config.json`, stopping at the first `.git` boundary
   (or after 64 levels if none is found). A project opts into its own private
   store simply by creating that file at its own repository root — nothing else
   changes; every command works identically once it exists.
2. **Global**: `$KNOWLEDGE_STORE_HOME/config.json`, defaulting to
   `~/.agents/knowledge-store/config.json` when that environment variable is
   unset — a single database shared by every project that hasn't opted into its
   own store. This is deliberate: it lets agents retrieve cross-project context
   regardless of which checkout invoked them, without every project needing to
   set anything up.

An explicit `--config <path>` always wins over both tiers.

Because the global tier is shared, `SECURITY.md`'s "use separate stores or
enforced partitions for materially different classifications or tenants" rule
rests on two mechanisms together: a project with materially different
requirements should use tier 1 (its own store) rather than the shared default,
and every ingestion/retrieval call against the shared store should carry a
`--source` that identifies the originating project (the deterministic
dispatch-plan builder in `agents/orchestration/src/build_dispatch_plan.py`
already defaults `--source` to the repository directory name when a caller
doesn't supply one).

## Security boundary

Retrieved text is untrusted reference data, never executable instruction. Classification filters are exact-match and caller supplied in this demo; they are not production authorization. See `SECURITY.md` before connecting this store to an agent or importing real history.

## Quick start

Requires Python 3.10 or newer and uses only the standard library. Resolve a Python interpreter as described in `../RUNBOOK.md`; the examples below use `<python>`.

One-time global setup (creates the shared store's config; skip if you want a
project-local store instead and will always pass `--config`):

```sh
mkdir -p ~/.agents/knowledge-store
cp config.example.json ~/.agents/knowledge-store/config.json
```

```powershell
<python> -B -m unittest discover -s test -p "test_*.py"
<python> -B src/cli.py init
<python> -B src/cli.py ingest --input examples/chat-export.json --source legacy-model-export
<python> -B src/cli.py context --agent release-engineer --task-id REL-42 --query "How are production releases approved?" --classification internal --top 5
```

Commands run from any directory: give `src/cli.py` its full path, e.g.
`python3 /path/to/this/checkout/agents/knowledge-store/src/cli.py context ...` —
no `cd` into `agents/knowledge-store` required.

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

Without `--config`, configuration is read using the project-local-then-global resolution above; if no config file exists at the resolved location, built-in defaults apply relative to that same directory. An existing config resolves its database path relative to the config directory. A supplied `--config` path must exist and contain a JSON object; otherwise the command fails closed.

`context` is the agent-facing command. It returns a schema-versioned bundle containing trust requirements, citations, and retrieved passages. `search` is a lower-level diagnostic command. Both require an explicit classification and apply exact-match classification and optional source filtering before ranking. `--top` must be an integer from 1 through 20, enforcing the orchestration policy limit.

`context` records `query_hash`, `task_id`, `agent`, `classification`, `source_filter`, embedding provider/model, requested top, result count, and creation time. It does not record an authenticated subject, tenant/project/environment scope, authorization decision or policy version, nor returned chunk/citation identifiers. Production auditing must add those fields and derive access from authenticated claims.

Read-only retrieval means agents cannot mutate stored content or lifecycle state. Opening any command, including `context`, can nevertheless create the database directory, SQLite file, schema, and WAL files; `context` also writes retrieval metadata. Grant that operational write access separately from content-steward authority. Citations use `source`, `conversation_id`, `message_id`, `chunk_id`, `content_hash`, `created_at`, and `classification`. The database retains `source_uri` for steward provenance, but retrieval output omits it by default because it may expose a local path. `content_hash` covers stored redacted content, not the original source.

Citations are point-in-time references, not immutable or permanently stable identifiers: re-ingestion can update content under the same source/conversation/message identity. Preserve each retrieved bundle plus its integrity hash for review/compliance evidence until the store provides versioned or append-only content and audits returned result snapshots.

The demo has no retention or deletion commands. Its ingestion response reports only run ID, message count, and chunk count; redaction and embedding summaries require supplemental steward records until implemented.

## Compatibility

The Python implementation retains the existing SQLite tables, indexes, identifiers, SHA-256 hashes, JSON vector encoding, hashing-vector algorithm, and provider/model selection. Existing databases are opened in place. Rows whose stored embedding dimension does not match the configured dimension are excluded rather than scored; re-ingest after changing provider, model, or dimensions. Back up the database before any runtime migration and never mix implementations against one database concurrently.
