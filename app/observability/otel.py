"""OpenTelemetry export over OTLP/HTTP: traces, metrics and logs.

Traces go to Langfuse and to any OTLP backend, both when both are configured: Langfuse
reads the LLM-specific attributes, a generic backend (Grafana, Jaeger, Datadog) correlates
them with metrics and logs. Metrics and logs need the OTLP endpoint, since Langfuse only
ingests traces. Nothing is exported unless configured.
"""

import base64
import logging
from dataclasses import dataclass
from urllib.parse import unquote

from opentelemetry import context, metrics, trace
from opentelemetry._logs import SeverityNumber, set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

TRACES_PATH = "/v1/traces"
METRICS_PATH = "/v1/metrics"
LOGS_PATH = "/v1/logs"
LANGFUSE_OTEL_PATH = "/api/public/otel"
# Short enough for a dashboard to move while you watch a demo; cheap at PoC volumes.
METRIC_EXPORT_INTERVAL_MS = 10_000
APP_LOGGER = "app"
_SEVERITY = {
    logging.DEBUG: SeverityNumber.DEBUG,
    logging.INFO: SeverityNumber.INFO,
    logging.WARNING: SeverityNumber.WARN,
    logging.ERROR: SeverityNumber.ERROR,
    logging.CRITICAL: SeverityNumber.FATAL,
}


@dataclass(frozen=True)
class OtlpTarget:
    endpoint: str
    headers: dict[str, str]


class OtelLogHandler(logging.Handler):
    """Forwards log records to OpenTelemetry, linked to the span that is active.

    Written here because the SDK's own handler is deprecated in favour of an extra package.
    """

    def __init__(self, provider: LoggerProvider) -> None:
        super().__init__(level=logging.INFO)
        self._logger = provider.get_logger(APP_LOGGER)

    def emit(self, record: logging.LogRecord) -> None:
        self._logger.emit(
            timestamp=int(record.created * 1e9),
            context=context.get_current(),
            severity_number=_SEVERITY.get(record.levelno, SeverityNumber.INFO),
            severity_text=record.levelname,
            body=record.getMessage(),
            attributes={"logger.name": record.name},
        )


@dataclass(frozen=True)
class Telemetry:
    """What was configured, so the application can flush and stop it on shutdown."""

    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    logger_provider: LoggerProvider | None = None
    log_handler: logging.Handler | None = None

    def shutdown(self) -> None:
        # Flushes what is still batched; each provider exports its last data here.
        if self.log_handler is not None:
            logging.getLogger(APP_LOGGER).removeHandler(self.log_handler)
            self.log_handler.close()
        for provider in (self.tracer_provider, self.meter_provider, self.logger_provider):
            if provider is not None:
                provider.shutdown()


def trace_targets(settings: Settings) -> tuple[OtlpTarget, ...]:
    """Every backend that receives spans: Langfuse, the OTLP endpoint, or both."""
    targets = (langfuse_target(settings), otlp_target(settings, TRACES_PATH))
    return tuple(target for target in targets if target is not None)


def langfuse_target(settings: Settings) -> OtlpTarget | None:
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    credentials = (
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key.get_secret_value()}"
    )
    token = base64.b64encode(credentials.encode()).decode()
    endpoint = f"{settings.langfuse_host.rstrip('/')}{LANGFUSE_OTEL_PATH}{TRACES_PATH}"
    return OtlpTarget(endpoint, {"Authorization": f"Basic {token}"})


def otlp_target(settings: Settings, signal_path: str) -> OtlpTarget | None:
    """The OTLP endpoint for one signal. OTLP_ENDPOINT may be the base URL or a /v1/traces URL."""
    if not settings.otlp_endpoint:
        return None
    base = settings.otlp_endpoint.rstrip("/").removesuffix(TRACES_PATH)
    raw_headers = settings.otlp_headers.get_secret_value() if settings.otlp_headers else ""
    return OtlpTarget(f"{base}{signal_path}", _parse_headers(raw_headers))


def configure_telemetry(settings: Settings) -> Telemetry:
    resource = Resource.create({"service.name": settings.service_name})
    logger_provider, log_handler = _configure_logs(settings, resource)
    return Telemetry(
        tracer_provider=_configure_traces(settings, resource),
        meter_provider=_configure_metrics(settings, resource),
        logger_provider=logger_provider,
        log_handler=log_handler,
    )


def _configure_traces(settings: Settings, resource: Resource) -> TracerProvider | None:
    targets = trace_targets(settings)
    if not targets:
        return None
    provider = TracerProvider(resource=resource)
    for target in targets:
        exporter = OTLPSpanExporter(endpoint=target.endpoint, headers=target.headers)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def _configure_metrics(settings: Settings, resource: Resource) -> MeterProvider | None:
    target = otlp_target(settings, METRICS_PATH)
    if target is None:
        return None
    exporter = OTLPMetricExporter(endpoint=target.endpoint, headers=target.headers)
    reader = PeriodicExportingMetricReader(
        exporter, export_interval_millis=METRIC_EXPORT_INTERVAL_MS
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


def _configure_logs(
    settings: Settings, resource: Resource
) -> tuple[LoggerProvider | None, logging.Handler | None]:
    target = otlp_target(settings, LOGS_PATH)
    if target is None:
        return None, None
    provider = LoggerProvider(resource=resource)
    exporter = OTLPLogExporter(endpoint=target.endpoint, headers=target.headers)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)
    # The same event lines as the console, as log records linked to the active span.
    handler = OtelLogHandler(provider)
    logging.getLogger(APP_LOGGER).addHandler(handler)
    return provider, handler


def _parse_headers(raw: str) -> dict[str, str]:
    """Parse "key=value,key2=value2" with percent-encoded values (the OTLP headers format)."""
    pairs = (item.split("=", 1) for item in raw.split(",") if "=" in item)
    return {key.strip(): unquote(value.strip()) for key, value in pairs}
