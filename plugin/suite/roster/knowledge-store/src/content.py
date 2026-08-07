"""Content redaction, injection indicators, and chunking."""

from __future__ import annotations

import re
from typing import Any


SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-]+=*", re.IGNORECASE)),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("generic-secret", re.compile(r"\b(api[_-]?key|secret|password|token)\s*[:=]\s*[\"']?[^\s,\"']{8,}[\"']?", re.IGNORECASE)),
]
INJECTION_PATTERNS = [
    re.compile(r"ignore (?:all |any )?(?:previous|prior|above) instructions", re.IGNORECASE),
    re.compile(r"reveal (?:the )?(?:system|developer) prompt", re.IGNORECASE),
    re.compile(r"act as (?:the )?system", re.IGNORECASE),
    re.compile(r"bypass (?:security|policy|approval|guardrail)", re.IGNORECASE),
    re.compile(r"do not tell (?:the )?user", re.IGNORECASE),
]


def protect_content(content: str, enabled: bool = True) -> dict[str, Any]:
    protected = content
    redactions: list[str] = []
    if enabled:
        for label, pattern in SECRET_PATTERNS:
            def replacement(_: re.Match[str], current_label: str = label) -> str:
                redactions.append(current_label)
                return f"[REDACTED:{current_label}]"
            protected = pattern.sub(replacement, protected)
    return {
        "content": protected,
        "redactions": redactions,
        "injection_risk": any(pattern.search(protected) for pattern in INJECTION_PATTERNS),
    }


def chunk_text(text: str, config: dict[str, int]) -> list[str]:
    maximum = config["max_characters"]
    overlap = config["overlap_characters"]
    if len(text) <= maximum:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + maximum, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end + 1), text.rfind(". ", start, end + 1))
            if boundary > start + int(maximum * 0.55):
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks
