import json
import logging
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from app.adapters.llm.scripted_llm import call_tool, say
from app.config import Settings
from app.domain.errors import LLMError
from app.domain.models import Usage
from app.observability.cost_tracker import estimate_cost_usd
from app.observability.otel import otlp_target
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


def test_tracing_is_off_by_default() -> None:
    assert otlp_target(Settings(_env_file=None)) is None


def test_langfuse_keys_build_the_otlp_target() -> None:
    settings = Settings(
        _env_file=None,
        langfuse_public_key="pk",
        langfuse_secret_key=SecretStr("sk"),
        langfuse_host="https://langfuse.example/",
    )

    target = otlp_target(settings)

    assert target == (
        "https://langfuse.example/api/public/otel/v1/traces",
        {"Authorization": "Basic cGs6c2s="},
    )


def test_generic_otlp_endpoint_and_headers() -> None:
    settings = Settings(
        _env_file=None,
        otlp_endpoint="http://collector:4318",
        otlp_headers=SecretStr("x-team=core, x-env=dev"),
    )

    assert otlp_target(settings) == (
        "http://collector:4318/v1/traces",
        {"x-team": "core", "x-env": "dev"},
    )


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

    assert otlp_target(settings) == (
        "http://collector:4318/v1/traces",
        {"Authorization": "Basic abc="},
    )


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
