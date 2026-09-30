"""Optional span export over OTLP/HTTP: Langfuse, or any OpenTelemetry backend.

Nothing is exported unless credentials or an endpoint are configured.
"""

import base64
from urllib.parse import unquote

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

TRACES_PATH = "/v1/traces"
LANGFUSE_OTEL_PATH = "/api/public/otel"


def otlp_target(settings: Settings) -> tuple[str, dict[str, str]] | None:
    """Where to send spans and with which headers, or None when tracing is off."""
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        credentials = (
            f"{settings.langfuse_public_key}:{settings.langfuse_secret_key.get_secret_value()}"
        )
        token = base64.b64encode(credentials.encode()).decode()
        endpoint = f"{settings.langfuse_host.rstrip('/')}{LANGFUSE_OTEL_PATH}{TRACES_PATH}"
        return endpoint, {"Authorization": f"Basic {token}"}
    if settings.otlp_endpoint:
        raw_headers = settings.otlp_headers.get_secret_value() if settings.otlp_headers else ""
        base = settings.otlp_endpoint.rstrip("/")
        endpoint = base if base.endswith(TRACES_PATH) else f"{base}{TRACES_PATH}"
        return endpoint, _parse_headers(raw_headers)
    return None


def configure_tracing(settings: Settings) -> TracerProvider | None:
    target = otlp_target(settings)
    if target is None:
        return None
    endpoint, headers = target
    provider = TracerProvider(resource=Resource.create({"service.name": settings.service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    )
    trace.set_tracer_provider(provider)
    return provider


def _parse_headers(raw: str) -> dict[str, str]:
    """Parse "key=value,key2=value2" with percent-encoded values (the OTLP headers format)."""
    pairs = (item.split("=", 1) for item in raw.split(",") if "=" in item)
    return {key.strip(): unquote(value.strip()) for key, value in pairs}
