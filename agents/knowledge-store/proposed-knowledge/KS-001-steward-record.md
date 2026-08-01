# Steward Record: KS-001-compose-runtime-lessons

Follows `agents/workflows/knowledge-ingestion.md`.

## 1. Ownership, classification, retention

- Source: this repository's own troubleshooting note from local Compose debugging on 2026-07-21 (no third-party export, no external chat content).
- Owner/processing authority: repository maintainer (Daniel Eagy).
- Intended use: operational knowledge for backend, infrastructure, test, code-review, and documentation agents working on local Compose/PostgreSQL/Vite runtime issues.
- Classification: internal. Tenant/audience: this project (`deagy/cadre`) only.
- Retention: indefinite as operational knowledge, subject to future correction/deletion by the steward; no legal-hold or third-party consent constraints apply since content is self-authored technical notes.

## 2. Security/compliance pre-check

Reviewed full content before staging: technical troubleshooting notes only (container labels, mount paths, permission behavior, dev-server config flags). No secrets, credentials, personal data, or customer data present. No external embedding provider used (offline hashing backend — no content left the local machine).

## 3. Normalization and sample verification

Source markdown converted to one canonical-schema conversation (a single assistant-role message, `created_at: 2026-07-21T00:00:00Z`) preserving the original text verbatim. Diffed against the proposed note to confirm no content drift introduced by normalization. Note: the ingested `conversation_id` predates this file's rename to `KS-001-*` and does not match the current filename prefix — cosmetic only, does not affect retrieval or citation integrity.

## 4. Redaction / injection detection

Ingested through the standard `protect_content` pipeline (`agents/knowledge-store/src/content.py`). Retrieval results confirm `untrusted_instruction_risk: false` and content unchanged from source (no secret-shaped strings present to redact).

## 5. Ingestion

- Command: `cadre knowledge ingest --input <staged-file> --source deagy/cadre --classification internal`
- Run ID: `097efaac-3bd8-4498-b198-4e10c4637074`
- Result: 1 message, 1 chunk.
- Embedding provider/model: offline hashing backend (demo default; no remote/semantic provider configured or approved for this store).
- Config: project-local store (`.agents/knowledge-store/config.json`), not the cross-project shared default.

## 6. Retrieval evaluation

Ran representative queries via `cadre knowledge context` (task-id `rag-capability-2026-07-31`):

- Positive (infrastructure-provisioner, "PostgreSQL 18 Docker Compose volume mount path"): retrieved, score 0.288, correct citation fields present, `untrusted_instruction_risk: false`.
- Positive (application-engineer, "Vite dev server read-only container node_modules write error"): retrieved, score 0.051.
- Negative (security-reviewer, "OAuth token refresh rotation policy" — unrelated topic): same chunk returned only because the corpus has a single item, but scored -0.013 (below both positive queries), showing the hashing embedder correctly ranks it least relevant.
- Source-scope isolation test (`--source some-other-project` instead of `deagy/cadre`): 0 results, confirming the source partition filter works.

Caveat: with a one-chunk corpus, relevance *ranking* is meaningfully testable but relevance *filtering* (would an unrelated query be excluded rather than merely ranked last) is not — that needs a larger corpus to evaluate properly. This is a known limitation of the offline hashing embedder, not a new finding (see `SECURITY.md` "Known limitations").

## 7. Evidence

This record plus the ingestion run ID above constitute the ingestion evidence trail. No raw secrets or third-party content were copied here.

## 8. Staging cleanup

No separate raw staging export existed outside this repository — the source was already the committed `KS-001-compose-runtime-lessons.md` proposal file, which remains as the reviewable record (status updated, not deleted).

## Approval

Steward-workflow steps 1-8 completed by knowledge-store-steward role dispatch under `run-agent-orchestration`, human-directed via explicit request to "ingest the sample source and run the steward workflow" (2026-07-31). No production/destructive action involved — local SQLite store only.
