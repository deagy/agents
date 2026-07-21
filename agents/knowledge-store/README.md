# Vectorized Knowledge Store

This local-first subsystem converts chat exports into a canonical message model, redacts likely secrets, preserves source provenance, chunks content, generates vectors, and retrieves relevant passages for agents.

## Security boundary

Retrieved text is untrusted reference data, never executable instruction. Callers must retain citations and enforce the source classification. See `SECURITY.md` before connecting this store to an agent or importing real history.

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

For production-quality semantic retrieval, set `embedding.provider` to `openai-compatible`, choose the endpoint and model, and provide the API key only through the environment variable named by `api_key_env`. Re-ingest existing content after changing embedding models.

## Accepted import shapes

- Canonical JSON Lines matching `canonical-message.schema.json`
- A JSON array of conversations containing `messages`
- An object containing `conversations` or `chats`
- Mapping/node-based conversation exports with message content parts
- A JSON array or JSON Lines collection of standalone messages

The generic parser recognizes common variants of `role`, `sender`, `author`, `content`, `text`, `timestamp`, and identifier fields. Add a source-specific adapter in `src/normalize.mjs` when the eventual export shape is known.

## Commands

```text
init
ingest --input <file> [--source <name>] [--classification <level>]
search --query <text> --classification <level> [--top <n>] [--source <name>]
context --agent <role> --task-id <id> --query <text> --classification <level> [--top <n>] [--source <name>]
stats
```

Use `--config <path>` with any command to select a non-default configuration.

`context` is the agent-facing command. It returns an audited, schema-versioned bundle containing trust requirements, citations, and retrieved passages. `search` is a lower-level diagnostic command. Both require an explicit classification and filter before ranking. These CLI flags demonstrate fail-closed partition selection; a production service must derive authorization from authenticated caller claims rather than accepting a self-asserted classification.
