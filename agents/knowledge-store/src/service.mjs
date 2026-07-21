import { createHash } from 'node:crypto';
import { normalizeFile } from './normalize.mjs';
import { protectContent, chunkText } from './content.mjs';
import { embedTexts, cosineSimilarity } from './embeddings.mjs';
import { beginRun, completeRun, failRun, loadChunks, saveMessage } from './database.mjs';

export async function ingestFile(db, config, options) {
  if (!['public', 'internal', 'confidential', 'restricted'].includes(options.classification)) {
    throw new Error(`Invalid classification: ${options.classification}`);
  }
  const messages = normalizeFile(options.input, {
    source: options.source,
    classification: options.classification
  });
  const runId = beginRun(db, options.source, messages[0]?.source_uri ?? null);
  let chunkCount = 0;
  try {
    for (const message of messages) {
      const protectedContent = protectContent(message.content, config.ingestion.redact_secrets);
      const chunks = chunkText(protectedContent.content, config.chunking);
      const vectors = await embedTexts(chunks, config.embedding);
      saveMessage(db, message, protectedContent, chunks, vectors, config.embedding);
      chunkCount += chunks.length;
    }
    completeRun(db, runId, messages.length, chunkCount);
    return { run_id: runId, messages: messages.length, chunks: chunkCount };
  } catch (error) {
    failRun(db, runId, error);
    throw error;
  }
}

export async function searchStore(db, config, query, options = {}) {
  if (!options.classification) throw new Error('A classification filter is required');
  const [queryVector] = await embedTexts([query], config.embedding);
  const limit = Math.max(1, Math.min(Number(options.top ?? 5), 100));
  return loadChunks(db, config.embedding, options)
    .map((row) => ({
      score: cosineSimilarity(queryVector, JSON.parse(row.embedding_json)),
      citation: {
        source: row.source,
        source_uri: row.source_uri,
        conversation_id: row.conversation_id,
        conversation_title: row.conversation_title,
        message_id: row.message_id,
        chunk_id: row.chunk_id,
        chunk_ordinal: row.ordinal,
        content_hash: row.content_hash,
        created_at: row.created_at,
        classification: row.classification
      },
      role: row.role,
      content: row.content,
      untrusted_instruction_risk: Boolean(row.injection_risk)
    }))
    .filter((result) => Number.isFinite(result.score))
    .sort((left, right) => right.score - left.score)
    .slice(0, limit);
}

export function stableQueryId(query) {
  return createHash('sha256').update(query).digest('hex').slice(0, 16);
}
