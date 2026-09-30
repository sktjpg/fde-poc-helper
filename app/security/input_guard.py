"""Guard 1: what the user sends, before it reaches the model."""

import unicodedata

from app.domain.errors import InputRejectedError

# Invisible characters used to hide text from a human reviewer: zero-width space, BOM,
# and the bidirectional overrides and isolates. Joiners (ZWJ, ZWNJ) are kept because
# emoji sequences and several scripts need them.
_HIDDEN = frozenset("\u200b\ufeff\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def check_input(text: str, *, max_chars: int) -> str:
    """Return the cleaned input, or raise InputRejectedError."""
    if len(text) > max_chars:
        raise InputRejectedError(f"Input is longer than {max_chars} characters")
    cleaned = "".join(ch for ch in text if _is_allowed(ch)).strip()
    if not cleaned:
        raise InputRejectedError("Input is empty")
    return cleaned


def _is_allowed(ch: str) -> bool:
    if ch in "\n\t":
        return True
    return ch not in _HIDDEN and unicodedata.category(ch) != "Cc"
