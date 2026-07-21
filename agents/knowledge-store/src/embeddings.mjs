import { createHash } from 'node:crypto';

function normalize(vector) {
  const magnitude = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  return magnitude ? vector.map((value) => value / magnitude) : vector;
}

function hashingEmbedding(text, dimensions) {
  const words = text.toLowerCase().match(/[\p{L}\p{N}_-]+/gu) ?? [];
  const features = [...words];
  for (let index = 0; index + 1 < words.length; index += 1) {
    features.push(`${words[index]}::${words[index + 1]}`);
  }
  const vector = new Array(dimensions).fill(0);
  for (const feature of features) {
    const digest = createHash('sha256').update(feature).digest();
    const position = digest.readUInt32LE(0) % dimensions;
    const sign = digest.readUInt32LE(4) % 2 === 0 ? 1 : -1;
    vector[position] += sign;
  }
  return normalize(vector);
}

async function remoteEmbeddings(texts, config) {
  if (!config.base_url || config.base_url.includes('example.invalid')) {
    throw new Error('Set embedding.base_url for the openai-compatible provider');
  }
  const key = process.env[config.api_key_env];
  if (!key) throw new Error(`Missing embedding credential in ${config.api_key_env}`);
  const response = await fetch(`${config.base_url.replace(/\/$/, '')}/embeddings`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
    body: JSON.stringify({ model: config.model, input: texts })
  });
  if (!response.ok) throw new Error(`Embedding endpoint returned ${response.status}: ${await response.text()}`);
  const payload = await response.json();
  const ordered = [...payload.data].sort((a, b) => a.index - b.index).map((item) => item.embedding);
  if (ordered.length !== texts.length || ordered.some((vector) => !Array.isArray(vector))) {
    throw new Error('Embedding endpoint returned an invalid response');
  }
  return ordered.map(normalize);
}

export async function embedTexts(texts, config) {
  if (config.provider === 'hashing') {
    return texts.map((text) => hashingEmbedding(text, config.dimensions));
  }
  const vectors = [];
  for (let start = 0; start < texts.length; start += config.batch_size) {
    vectors.push(...await remoteEmbeddings(texts.slice(start, start + config.batch_size), config));
  }
  return vectors;
}

export function cosineSimilarity(left, right) {
  if (left.length !== right.length) return Number.NEGATIVE_INFINITY;
  let score = 0;
  for (let index = 0; index < left.length; index += 1) score += left[index] * right[index];
  return score;
}
