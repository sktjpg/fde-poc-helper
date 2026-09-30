import json
import logging
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from app.adapters.llm.scripted_llm import call_tool, say
from app.config import Settings
from app.domain.errors import LLMError
from app.domain.models import Usage
from app.observability.cost_tracker import estimate_cost_usd
from app.observability.otel import (
    LOGS_PATH,
    METRICS_PATH,
    OtelLogHandler,
    OtlpTarget,
    Telemetry,
    configure_telemetry,
    otlp_target,
    trace_targets,
)
from app.observability.tracer import MAX_PAYLOAD_CHARS, PAYLOAD_TRUNCATED, span_payload
from tests.conftest import ServiceFactory

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def tracer_provider() -> None:
    # The global provider can only be set once per process.
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
    trace.set_tracer_provider(provider)


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    EXPORTER.clear()
    yield EXPORTER
    EXPORTER.clear()


async def test_a_run_produces_one_trace_with_llm_and_tool_spans(
    make_service: ServiceFactory, spans: InMemorySpanExporter
) -> None:
    service = make_service([call_tool("calculator", operation="add", a=2, b=3), say("5")])

    result = await service.answer("2 + 3?")

    finished = spans.get_finished_spans()
    assert sorted(span.name for span in finished) == [
        "agent.run",
        "execute_tool calculator",
        "llm.call",
        "llm.call",
    ]
    trace_ids = {format(span.context.trace_id, "032x") for span in finished}
    assert trace_ids == {result.trace_id}
    root = next(span for span in finished if span.name == "agent.run")
    assert root.attributes is not None
    assert root.attributes["agent.status"] == "completed"


async def test_spans_carry_what_went_in_and_what_came_out(
    make_service: ServiceFactory, spans: InMemorySpanExporter
) -> None:
    service = make_service([call_tool("calculator", operation="add", a=2, b=3), say("It is 5")])

    await service.answer("2 + 3?")

    by_name = {span.name: dict(span.attributes or {}) for span in spans.get_finished_spans()}
    assert by_name["agent.run"]["input.value"] == "2 + 3?"
    assert by_name["agent.run"]["output.value"] == "It is 5"
    tool_input = json.loads(str(by_name["execute_tool calculator"]["input.value"]))
    assert tool_input == {"operation": "add", "a": 2, "b": 3}
    assert "5" in str(by_name["execute_tool calculator"]["output.value"])
    assert "It is 5" in str(by_name["llm.call"]["output.value"])


async def test_secrets_never_reach_a_span(
    make_service: ServiceFactory, spans: InMemorySpanExporter
) -> None:
    leaked = "sk-abcdefghijklmnop1234"
    service = make_service([call_tool("lookup", api_key=leaked), say(f"key: {leaked}")])

    await service.answer("hi")

    recorded = json.dumps(
        [dict(span.attributes or {}) for span in spans.get_finished_spans()], default=str
    )
    assert leaked not in recorded


def test_span_payloads_are_bounded() -> None:
    payload = span_payload("x" * (MAX_PAYLOAD_CHARS + 500))

    assert len(payload) == MAX_PAYLOAD_CHARS + len(PAYLOAD_TRUNCATED)
    assert payload.endswith(PAYLOAD_TRUNCATED)


def test_telemetry_is_off_by_default() -> None:
    settings = Settings(_env_file=None)

    assert trace_targets(settings) == ()
    assert configure_telemetry(settings) == Telemetry()


def test_langfuse_keys_build_the_otlp_target() -> None:
    settings = Settings(
        _env_file=None,
        langfuse_public_key="pk",
        langfuse_secret_key=SecretStr("sk"),
        langfuse_host="https://langfuse.example/",
    )

    assert trace_targets(settings) == (
        OtlpTarget(
            "https://langfuse.example/api/public/otel/v1/traces",
            {"Authorization": "Basic cGs6c2s="},
        ),
    )


def test_the_otlp_endpoint_receives_traces_metrics_and_logs() -> None:
    settings = Settings(
        _env_file=None,
        otlp_endpoint="http://collector:4318",
        otlp_headers=SecretStr("x-team=core, x-env=dev"),
    )
    headers = {"x-team": "core", "x-env": "dev"}

    assert trace_targets(settings) == (OtlpTarget("http://collector:4318/v1/traces", headers),)
    assert otlp_target(settings, METRICS_PATH) == OtlpTarget(
        "http://collector:4318/v1/metrics", headers
    )
    assert otlp_target(settings, LOGS_PATH) == OtlpTarget("http://collector:4318/v1/logs", headers)


def test_traces_go_to_langfuse_and_the_otlp_endpoint_when_both_are_set() -> None:
    settings = Settings(
        _env_file=None,
        langfuse_public_key="pk",
        langfuse_secret_key=SecretStr("sk"),
        langfuse_host="https://langfuse.example",
        otlp_endpoint="http://collector:4318",
    )

    endpoints = [target.endpoint for target in trace_targets(settings)]

    assert endpoints == [
        "https://langfuse.example/api/public/otel/v1/traces",
        "http://collector:4318/v1/traces",
    ]


def test_cost_uses_the_price_table() -> None:
    usage = Usage(input_tokens=500_000, output_tokens=100_000)

    assert estimate_cost_usd("claude-sonnet-5-5", usage) == 2.0
    assert estimate_cost_usd("unknown-model", usage) is None


async def test_a_cost_reported_by_the_adapter_wins_over_the_price_table(
    make_service: ServiceFactory,
) -> None:
    reply = say("hi").model_copy(update={"cost_usd": 0.25})

    result = await make_service([reply]).answer("hello")

    assert result.cost_usd == 0.25


def test_otlp_headers_are_percent_decoded_and_the_path_is_not_doubled() -> None:
    settings = Settings(
        _env_file=None,
        otlp_endpoint="http://collector:4318/v1/traces",
        otlp_headers=SecretStr("Authorization=Basic%20abc%3D"),
    )

    assert trace_targets(settings) == (
        OtlpTarget("http://collector:4318/v1/traces", {"Authorization": "Basic abc="}),
    )
    metrics = otlp_target(settings, METRICS_PATH)
    assert metrics is not None
    assert metrics.endpoint == "http://collector:4318/v1/metrics"


async def test_a_failed_run_is_logged_with_its_trace_id(
    make_service: ServiceFactory, caplog: pytest.LogCaptureFixture
) -> None:
    service = make_service([LLMError("provider down")])

    with caplog.at_level(logging.INFO, logger="app"), pytest.raises(LLMError):
        await service.answer("hi")

    (event,) = [json.loads(record.message) for record in caplog.records]
    assert event["event"] == "agent_failed"
    assert event["error"] == "LLMError"
    assert len(event["trace_id"]) == 32


def test_log_records_are_exported_linked_to_the_active_span(
    spans: InMemorySpanExporter,
) -> None:
    exporter = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]  # SDK lacks the hint
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    logger = logging.getLogger("tests.otel_logs")
    handler = OtelLogHandler(provider)
    logger.addHandler(handler)

    try:
        with trace.get_tracer("tests").start_as_current_span("work") as span:
            logger.warning('{"event": "probe"}')
    finally:
        logger.removeHandler(handler)

    (exported,) = exporter.get_finished_logs()
    assert exported.log_record.body == '{"event": "probe"}'
    assert exported.log_record.severity_text == "WARNING"
    assert exported.log_record.trace_id == span.get_span_context().trace_id
