"""Guard 2: untrusted content (tool results, retrieved documents) entering the context."""

import re
from dataclasses import dataclass

MAX_CONTENT_CHARS = 8000
TRUNCATION_NOTICE = "\n[truncated]"

# Heuristic only: used to flag and trace, never as the sole protection.
_INJECTION_PATTERNS = re.compile(
    r"(ignore|disregard|forget)\s+((all|any|the|your|these|those)\s+)*"
    r"(previous|prior|above|earlier|system)\s+(instructions|prompts?|rules)"
    r"|(reveal|print|show|repeat)\s+((the|your)\s+)?system\s+prompt",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FilteredContent:
    text: str
    suspicious: bool
    truncated: bool


def filter_untrusted(text: str, *, max_chars: int = MAX_CONTENT_CHARS) -> FilteredContent:
    truncated = len(text) > max_chars
    bounded = text[:max_chars] + TRUNCATION_NOTICE if truncated else text
    return FilteredContent(
        text=bounded,
        suspicious=_INJECTION_PATTERNS.search(text) is not None,
        truncated=truncated,
    )
