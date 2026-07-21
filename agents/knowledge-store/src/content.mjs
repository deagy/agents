const secretPatterns = [
  { label: 'private-key', regex: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/g },
  { label: 'bearer-token', regex: /\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi },
  { label: 'aws-access-key', regex: /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g },
  { label: 'github-token', regex: /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b/g },
  { label: 'generic-secret', regex: /\b(api[_-]?key|secret|password|token)\s*[:=]\s*["']?[^\s,"']{8,}["']?/gi }
];

const injectionPatterns = [
  /ignore (?:all |any )?(?:previous|prior|above) instructions/i,
  /reveal (?:the )?(?:system|developer) prompt/i,
  /act as (?:the )?system/i,
  /bypass (?:security|policy|approval|guardrail)/i,
  /do not tell (?:the )?user/i
];

export function protectContent(content, enabled = true) {
  let protectedContent = content;
  const redactions = [];
  if (enabled) {
    for (const pattern of secretPatterns) {
      protectedContent = protectedContent.replace(pattern.regex, () => {
        redactions.push(pattern.label);
        return `[REDACTED:${pattern.label}]`;
      });
    }
  }
  return {
    content: protectedContent,
    redactions,
    injectionRisk: injectionPatterns.some((pattern) => pattern.test(protectedContent))
  };
}

export function chunkText(text, { max_characters: maxCharacters, overlap_characters: overlap }) {
  if (text.length <= maxCharacters) return [text];
  const chunks = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + maxCharacters, text.length);
    if (end < text.length) {
      const boundary = Math.max(text.lastIndexOf('\n\n', end), text.lastIndexOf('. ', end));
      if (boundary > start + Math.floor(maxCharacters * 0.55)) end = boundary + 1;
    }
    chunks.push(text.slice(start, end).trim());
    if (end >= text.length) break;
    start = Math.max(start + 1, end - overlap);
  }
  return chunks.filter(Boolean);
}
