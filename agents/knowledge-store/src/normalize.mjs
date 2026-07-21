import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const roles = new Set(['system', 'user', 'assistant', 'tool']);

function digest(value) {
  return createHash('sha256').update(String(value)).digest('hex');
}

function textOf(value) {
  if (typeof value === 'string') return value.trim();
  if (Array.isArray(value)) return value.map(textOf).filter(Boolean).join('\n').trim();
  if (!value || typeof value !== 'object') return '';
  if (Array.isArray(value.parts)) return textOf(value.parts);
  if (value.text !== undefined) return textOf(value.text);
  if (value.content !== undefined) return textOf(value.content);
  if (value.value !== undefined) return textOf(value.value);
  return '';
}

function dateOf(value) {
  if (value === undefined || value === null || value === '') return null;
  const numeric = typeof value === 'number' ? value : Number.NaN;
  const date = Number.isFinite(numeric)
    ? new Date(numeric < 1e12 ? numeric * 1000 : numeric)
    : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function roleOf(message) {
  const raw = message.role ?? message.sender ?? message.author?.role ?? message.author?.name;
  const normalized = String(raw ?? 'unknown').toLowerCase();
  if (roles.has(normalized)) return normalized;
  if (['human', 'customer'].includes(normalized)) return 'user';
  if (['ai', 'bot', 'model'].includes(normalized)) return 'assistant';
  return 'unknown';
}

function messagesOf(conversation) {
  if (Array.isArray(conversation.messages)) return conversation.messages;
  if (Array.isArray(conversation.chat)) return conversation.chat;
  if (Array.isArray(conversation.conversation)) return conversation.conversation;
  if (conversation.mapping && typeof conversation.mapping === 'object') {
    return Object.values(conversation.mapping)
      .map((node) => node?.message)
      .filter(Boolean)
      .sort((a, b) => (a.create_time ?? 0) - (b.create_time ?? 0));
  }
  return [];
}

function isMessage(value) {
  return value && typeof value === 'object' && (
    value.content !== undefined || value.text !== undefined || value.message !== undefined
  );
}

function canonicalMessage(message, context, index) {
  const content = textOf(message.content ?? message.text ?? message.message);
  if (!content) return null;
  const messageId = String(message.message_id ?? message.id ?? message.uuid ?? digest(
    `${context.source}|${context.conversationId}|${index}|${content}`
  ).slice(0, 24));
  return {
    source: context.source,
    source_uri: context.sourceUri,
    conversation_id: context.conversationId,
    conversation_title: context.title,
    message_id: messageId,
    role: roleOf(message),
    content,
    created_at: dateOf(message.created_at ?? message.timestamp ?? message.create_time ?? message.date),
    classification: context.classification,
    metadata: { source_format: context.sourceFormat }
  };
}

function parseInput(raw) {
  try {
    return { value: JSON.parse(raw), format: 'json' };
  } catch {
    const lines = raw.split(/\r?\n/).filter((line) => line.trim());
    return { value: lines.map((line, index) => {
      try { return JSON.parse(line); }
      catch { throw new Error(`Invalid JSON on JSONL line ${index + 1}`); }
    }), format: 'jsonl' };
  }
}

export function normalizeFile(inputPath, { source, classification }) {
  const absolute = path.resolve(process.cwd(), inputPath);
  const raw = fs.readFileSync(absolute, 'utf8');
  const { value, format } = parseInput(raw);
  const root = value?.conversations ?? value?.chats ?? value;
  const items = Array.isArray(root) ? root : [root];
  const results = [];

  if (items.every(isMessage) && !items.some((item) => messagesOf(item).length)) {
    const conversationId = digest(`${source}|${absolute}`).slice(0, 24);
    items.forEach((message, index) => {
      const canonical = canonicalMessage(message, {
        source, sourceUri: absolute, conversationId, title: null,
        classification, sourceFormat: format
      }, index);
      if (canonical) results.push(canonical);
    });
  } else {
    items.forEach((conversation, conversationIndex) => {
      const title = conversation?.title ?? conversation?.name ?? null;
      const conversationId = String(conversation?.conversation_id ?? conversation?.id ?? conversation?.uuid ?? digest(
        `${source}|${absolute}|${conversationIndex}|${title ?? ''}`
      ).slice(0, 24));
      messagesOf(conversation ?? {}).forEach((message, messageIndex) => {
        const canonical = canonicalMessage(message, {
          source, sourceUri: absolute, conversationId, title,
          classification, sourceFormat: conversation?.mapping ? 'mapping-json' : format
        }, messageIndex);
        if (canonical) results.push(canonical);
      });
    });
  }

  if (!results.length) throw new Error('No non-empty chat messages were recognized in the input');
  return results;
}
