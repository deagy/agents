import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';

function hash(value) {
  return createHash('sha256').update(value).digest('hex');
}

export function openStore(databasePath) {
  fs.mkdirSync(path.dirname(databasePath), { recursive: true });
  const db = new DatabaseSync(databasePath);
  db.exec('PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;');
  db.exec(`
    CREATE TABLE IF NOT EXISTS ingestion_runs (
      id TEXT PRIMARY KEY,
      source TEXT NOT NULL,
      source_uri TEXT,
      started_at TEXT NOT NULL,
      completed_at TEXT,
      status TEXT NOT NULL,
      message_count INTEGER NOT NULL DEFAULT 0,
      chunk_count INTEGER NOT NULL DEFAULT 0,
      error TEXT
    );
    CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY,
      source TEXT NOT NULL,
      source_uri TEXT,
      conversation_id TEXT NOT NULL,
      conversation_title TEXT,
      source_message_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      content_hash TEXT NOT NULL,
      created_at TEXT,
      classification TEXT NOT NULL,
      injection_risk INTEGER NOT NULL DEFAULT 0,
      redactions_json TEXT NOT NULL,
      metadata_json TEXT NOT NULL,
      ingested_at TEXT NOT NULL,
      UNIQUE(source, conversation_id, source_message_id)
    );
    CREATE TABLE IF NOT EXISTS chunks (
      id TEXT PRIMARY KEY,
      message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
      ordinal INTEGER NOT NULL,
      content TEXT NOT NULL,
      content_hash TEXT NOT NULL,
      embedding_provider TEXT NOT NULL,
      embedding_model TEXT NOT NULL,
      embedding_dimensions INTEGER NOT NULL,
      embedding_json TEXT NOT NULL,
      UNIQUE(message_id, ordinal, embedding_provider, embedding_model)
    );
    CREATE TABLE IF NOT EXISTS retrieval_runs (
      id TEXT PRIMARY KEY,
      query_hash TEXT NOT NULL,
      task_id TEXT NOT NULL,
      agent TEXT NOT NULL,
      classification TEXT NOT NULL,
      source_filter TEXT,
      embedding_provider TEXT NOT NULL,
      embedding_model TEXT NOT NULL,
      requested_top INTEGER NOT NULL,
      result_count INTEGER NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source);
    CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
    CREATE INDEX IF NOT EXISTS idx_messages_classification ON messages(classification);
    CREATE INDEX IF NOT EXISTS idx_chunks_model ON chunks(embedding_provider, embedding_model);
    CREATE INDEX IF NOT EXISTS idx_retrieval_runs_task ON retrieval_runs(task_id, agent);
  `);
  return db;
}

export function beginRun(db, source, sourceUri) {
  const id = randomUUID();
  db.prepare(`INSERT INTO ingestion_runs (id, source, source_uri, started_at, status)
    VALUES (?, ?, ?, ?, 'running')`).run(id, source, sourceUri, new Date().toISOString());
  return id;
}

export function completeRun(db, id, messageCount, chunkCount) {
  db.prepare(`UPDATE ingestion_runs SET completed_at = ?, status = 'complete', message_count = ?, chunk_count = ?
    WHERE id = ?`).run(new Date().toISOString(), messageCount, chunkCount, id);
}

export function failRun(db, id, error) {
  db.prepare(`UPDATE ingestion_runs SET completed_at = ?, status = 'failed', error = ? WHERE id = ?`)
    .run(new Date().toISOString(), String(error).slice(0, 2000), id);
}

export function saveMessage(db, message, protectedContent, chunks, vectors, embedding) {
  const id = hash(`${message.source}|${message.conversation_id}|${message.message_id}`);
  const now = new Date().toISOString();
  const upsert = db.prepare(`
    INSERT INTO messages (
      id, source, source_uri, conversation_id, conversation_title, source_message_id, role,
      content, content_hash, created_at, classification, injection_risk, redactions_json,
      metadata_json, ingested_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(source, conversation_id, source_message_id) DO UPDATE SET
      source_uri=excluded.source_uri, conversation_title=excluded.conversation_title,
      role=excluded.role, content=excluded.content, content_hash=excluded.content_hash,
      created_at=excluded.created_at, classification=excluded.classification,
      injection_risk=excluded.injection_risk, redactions_json=excluded.redactions_json,
      metadata_json=excluded.metadata_json, ingested_at=excluded.ingested_at
  `);
  db.exec('BEGIN');
  try {
    upsert.run(
      id, message.source, message.source_uri, message.conversation_id, message.conversation_title,
      message.message_id, message.role, protectedContent.content, hash(protectedContent.content),
      message.created_at, message.classification, protectedContent.injectionRisk ? 1 : 0,
      JSON.stringify(protectedContent.redactions), JSON.stringify(message.metadata), now
    );
    db.prepare('DELETE FROM chunks WHERE message_id = ?').run(id);
    const insertChunk = db.prepare(`INSERT INTO chunks (
      id, message_id, ordinal, content, content_hash, embedding_provider, embedding_model,
      embedding_dimensions, embedding_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`);
    chunks.forEach((chunk, ordinal) => {
      insertChunk.run(
        hash(`${id}|${ordinal}|${embedding.provider}|${embedding.model}`), id, ordinal,
        chunk, hash(chunk), embedding.provider, embedding.model, vectors[ordinal].length,
        JSON.stringify(vectors[ordinal])
      );
    });
    db.exec('COMMIT');
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }
}

export function loadChunks(db, embedding, filters = {}) {
  const clauses = ['c.embedding_provider = ?', 'c.embedding_model = ?'];
  const values = [embedding.provider, embedding.model];
  if (filters.source) { clauses.push('m.source = ?'); values.push(filters.source); }
  if (!filters.classification) throw new Error('A classification filter is required');
  clauses.push('m.classification = ?');
  values.push(filters.classification);
  return db.prepare(`SELECT
      c.id AS chunk_id, c.ordinal, c.content, c.content_hash, c.embedding_json,
      m.source, m.source_uri, m.conversation_id, m.conversation_title,
      m.source_message_id AS message_id, m.role, m.created_at, m.classification, m.injection_risk
    FROM chunks c JOIN messages m ON m.id = c.message_id
    WHERE ${clauses.join(' AND ')}`).all(...values);
}

export function recordRetrieval(db, retrieval) {
  const id = randomUUID();
  db.prepare(`INSERT INTO retrieval_runs (
    id, query_hash, task_id, agent, classification, source_filter,
    embedding_provider, embedding_model, requested_top, result_count, created_at
  ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
    id, retrieval.queryHash, retrieval.taskId, retrieval.agent, retrieval.classification,
    retrieval.source ?? null, retrieval.embedding.provider, retrieval.embedding.model,
    retrieval.requestedTop, retrieval.resultCount, new Date().toISOString()
  );
  return id;
}

export function storeStats(db) {
  const counts = db.prepare(`SELECT
    (SELECT COUNT(*) FROM messages) AS messages,
    (SELECT COUNT(*) FROM chunks) AS chunks,
    (SELECT COUNT(*) FROM retrieval_runs) AS retrieval_runs,
    (SELECT COUNT(*) FROM ingestion_runs WHERE status = 'complete') AS completed_runs,
    (SELECT COUNT(*) FROM ingestion_runs WHERE status = 'failed') AS failed_runs`).get();
  const sources = db.prepare('SELECT source, COUNT(*) AS messages FROM messages GROUP BY source ORDER BY source').all();
  return { ...counts, sources };
}
