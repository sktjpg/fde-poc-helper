"""Tracing: OpenTelemetry spans plus one redacted JSON log line per event.

Spans are no-ops until an exporter is configured (see otel.py), so the code is always
instrumented and costs nothing when tracing is off. Every event carries the trace_id, so
one lookup answers "what exactly happened in this run?".
"""

import json
import logging
import re
import uuid
from contextlib import AbstractContextManager
from typing import Any

from opentelemetry import trace

from app.security.output_filter import filter_output

REDACTED = "[redacted]"
SENSITIVE_WORDS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "apikey",
        "credential",
        "credentials",
    }
)
SENSITIVE_SUFFIXES = ("api_key", "access_key", "private_key")

# What went into and came out of a span. These two names are read by Langfuse, Phoenix
# and other LLM tracing backends, so the payload shows up without vendor-specific code.
INPUT_ATTRIBUTE = "input.value"
OUTPUT_ATTRIBUTE = "output.value"
MAX_PAYLOAD_CHARS = 4000
PAYLOAD_TRUNCATED = "...[truncated]"

_tracer = trace.get_tracer("app")


SpanAttributes = dict[str, str | int | float | bool]


def start_span(name: str, attributes: SpanAttributes | None = None) -> AbstractContextManager[Any]:
    return _tracer.start_as_current_span(name, attributes=attributes)


def current_trace_id() -> str:
    """The active OpenTelemetry trace id, or a fresh id when tracing is not configured."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else uuid.uuid4().hex


def redact(value: Any) -> Any:
    """Return a copy with sensitive keys masked and credential-shaped strings removed."""
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return filter_output(value)
    return value


def span_payload(value: Any) -> str:
    """Text for a span input or output: redacted and bounded.

    Spans leave the process and are stored by the tracing backend, so they get the same
    masking as the log and a size limit.
    """
    cleaned = redact(value)
    text = (
        cleaned
        if isinstance(cleaned, str)
        else json.dumps(cleaned, default=str, ensure_ascii=False)
    )
    if len(text) <= MAX_PAYLOAD_CHARS:
        return text
    return text[:MAX_PAYLOAD_CHARS] + PAYLOAD_TRUNCATED


def configure_logging(level: int = logging.INFO) -> None:
    """Send the application's event log to stderr. Without this, INFO events are dropped."""
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        app_logger.addHandler(handler)
        app_logger.propagate = False


def log_event(logger: logging.Logger, trace_id: str, event: str, **fields: Any) -> None:
    payload = {"trace_id": trace_id, "event": event, **redact(fields)}
    logger.info(json.dumps(payload, default=str))


def _is_sensitive(key: str) -> bool:
    # Whole words only: "token" is sensitive, "input_tokens" is a counter.
    lowered = key.lower()
    words = set(re.split(r"[^a-z0-9]+", lowered))
    return bool(words & SENSITIVE_WORDS) or lowered.endswith(SENSITIVE_SUFFIXES)
