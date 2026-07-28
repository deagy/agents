"""Canonical injection-pattern catalog.

Shared between agents/knowledge-store/src/content.py and
agents/orchestration/src/generate_global_plugin.py so that both code paths validate
against the same security policy. The list is organized as (category_label,
pattern_regex_string) tuples so that content neutralization can report which category
matched without echoing raw payloads, and so the generator can compile patterns for its own scan.

Referenced by:
  * agents/knowledge-store/src/content.py:INJECTION_PATTERNS (compiled at module load)
  * agents/orchestration/src/generate_global_plugin.py:_AGENT_DEFINITION_INJECTION_PATTERN_DEFS
"""

from __future__ import annotations

from typing import Iterable, Tuple

# Each entry is (category_label, pattern_regex_string). The regex string is compiled lazily
# by each consumer so they can choose their own flags (e.g., re.IGNORECASE).
INJECTION_PATTERN_DEFS: list[Tuple[str, str]] = [
    ("ignore-predecessor", r"ignore (?:all |any )?(?:previous|prior|above) instructions"),
    ("reveal-prompt", r"reveal (?:the )?(?:system|developer) prompt"),
    ("role-hijack", r"act as (?:the )?system"),
    ("guardrail-bypass", r"bypass (?:security|policy|approval|guardrail)"),
    ("silence-user", r"do not tell (?:the )?user"),
]


def iter_pattern_defs() -> Iterable[Tuple[str, str]]:
    """Yield (category_label, pattern_regex_string) tuples."""
    yield from INJECTION_PATTERN_DEFS
