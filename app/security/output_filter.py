"""Guard 3: what leaves the system. Masks credential-shaped strings."""

import re
from typing import Any

REDACTED = "[redacted]"

# Each pattern requires a digit in the token body, so ordinary hyphenated words
# ("risk-assessment-framework") are never mistaken for a key.
_HAS_DIGIT = r"(?=[A-Za-z0-9._~+/-]*\d)"
_SECRET_PATTERNS = re.compile(
    rf"\bsk-{_HAS_DIGIT}[A-Za-z0-9_-]{{16,}}"  # API keys in the common sk- format
    r"|\bAKIA[0-9A-Z]{16}\b"  # AWS access key ids
    rf"|\bBearer\s+{_HAS_DIGIT}[A-Za-z0-9._~+/-]{{16,}}=*"  # bearer tokens
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
)


def filter_output(text: str) -> str:
    return _SECRET_PATTERNS.sub(REDACTED, text)


def mask_secrets(value: Any) -> Any:
    """Return a copy of a nested structure with credential-shaped strings masked."""
    if isinstance(value, str):
        return filter_output(value)
    if isinstance(value, dict):
        return {key: mask_secrets(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [mask_secrets(item) for item in value]
    return value
