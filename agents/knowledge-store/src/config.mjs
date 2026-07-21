import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const defaults = {
  database: './data/knowledge.db',
  embedding: {
    provider: 'hashing',
    model: 'feature-hash-v1',
    dimensions: 384,
    base_url: null,
    api_key_env: 'KNOWLEDGE_EMBEDDING_API_KEY',
    batch_size: 32
  },
  chunking: { max_characters: 2400, overlap_characters: 240 },
  ingestion: { default_classification: 'internal', redact_secrets: true }
};

function merge(base, override) {
  const result = { ...base };
  for (const [key, value] of Object.entries(override ?? {})) {
    result[key] = value && typeof value === 'object' && !Array.isArray(value)
      ? merge(base[key] ?? {}, value)
      : value;
  }
  return result;
}

export function loadConfig(configPath) {
  const selected = configPath
    ? path.resolve(process.cwd(), configPath)
    : path.join(packageRoot, 'config.json');
  const exists = fs.existsSync(selected);
  const supplied = exists ? JSON.parse(fs.readFileSync(selected, 'utf8')) : {};
  const config = merge(defaults, supplied);
  const baseDirectory = exists ? path.dirname(selected) : packageRoot;
  config.database = path.resolve(baseDirectory, config.database);

  if (!['hashing', 'openai-compatible'].includes(config.embedding.provider)) {
    throw new Error(`Unsupported embedding provider: ${config.embedding.provider}`);
  }
  if (!Number.isInteger(config.embedding.dimensions) || config.embedding.dimensions < 32) {
    throw new Error('embedding.dimensions must be an integer of at least 32');
  }
  if (config.chunking.overlap_characters >= config.chunking.max_characters) {
    throw new Error('chunk overlap must be smaller than max_characters');
  }
  return config;
}
