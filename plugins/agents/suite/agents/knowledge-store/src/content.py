"""Content redaction, injection indicators, and chunking."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


# Ensure agents/shared is resolvable so we can pull the canonical injection-pattern
# catalog from agents.shared.injection_patterns without requiring an installed
# package. This keeps content.py self-contained for test runs that add only
# knowledge-store/src to sys.path (as the existing suite does).
_KNOWLEDGE_STORE_SRC = Path(__file__).resolve().parent
_AGENTS_ROOT = _KNOWLEDGE_STORE_SRC.parent  # agents/
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from agents.shared.injection_patterns import INJECTION_PATTERN_DEFS  # noqa: E402


SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-]+=*", re.IGNORECASE)),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("generic-secret", re.compile(r"\b(api[_-]?key|secret|password|token)\s*[:=]\s*[\"']?[^\s,\"']{8,}[\"']?", re.IGNORECASE)),
]

# Heuristic detector for untrusted injection patterns (CWE-94 / CWE-502).
# Each entry is ``(category_label, compiled_regex)`` so we can report which
# category matched during neutralization without echoing the raw payload.
# Source of truth: agents/shared/injection_patterns.py — this module compiles
# the regex strings there with ``re.IGNORECASE`` for content scanning.
INJECTION_PATTERNS = [
    (category, re.compile(pattern_string, re.IGNORECASE))
    for category, pattern_string in INJECTION_PATTERN_DEFS
]


_INJECTION_PLACEHOLDER = "[INJECTED_INSTRUCTION_REDACTED]"


def protect_content(content: str, enabled: bool = True) -> dict[str, Any]:
    """Redact secrets and actively neutralize untrusted injection patterns.

    SECRET_PATTERNS are replaced with ``[REDACTED:<label>]`` placeholders.
    INJECTION_PATTERNS (CWE-94 / CWE-502 heuristics) are *also* actively
    redacted — not merely flagged — so retrieved content cannot carry an
    injected instruction into the agent context.

    Returns a dict with:
      ``content``                 - redacted/neutralized text (safe to emit),
      ``redactions``              - list of secret labels that were redacted,
      ``injection_risk``          - True if any injection pattern was detected,
      ``neutralization_metadata`` - None when nothing was neutralized; otherwise
                                    a list of the matched injection categories.
    """
    protected = content
    redactions: list[str] = []
    injection_neutralized_categories: list[str] = []

    if enabled:
        for label, pattern in SECRET_PATTERNS:
            def replacement(_: re.Match[str], current_label: str = label) -> str:
                redactions.append(current_label)
                return f"[REDACTED:{current_label}]"
            protected = pattern.sub(replacement, protected)

        # Active neutralization of injection patterns (HIGH-severity fix):
        # detect on the original content so we do not miss patterns that a
        # prior secret-redaction pass would have partially altered, then
        # replace every match with a safe placeholder.
        for category, pattern in INJECTION_PATTERNS:
            if pattern.search(content):
                injection_neutralized_categories.append(category)
                protected = pattern.sub(_INJECTION_PLACEHOLDER, protected)

    neutralization_metadata: list[str] | None = (
        injection_neutralized_categories if injection_neutralized_categories else None
    )
    log.info(
        "protect_content completed: secret redactions=%s, injection_risk=%s, neutralized=%r",
        len(redactions), bool(injection_neutralized_categories), neutralization_metadata,
    )
    if neutralization_metadata:
        categories_str = ", ".join(neutralization_metadata)
        log.warning(
            "untrusted-instruction neutralized during retrieval; pattern categories: %s — raw payload not echoed",
            categories_str,
        )

    return {
        "content": protected,
        "redactions": redactions,
        "injection_risk": bool(injection_neutralized_categories),
        "neutralization_metadata": neutralization_metadata,
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
