from collections.abc import Iterator

import pytest
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader

from app.adapters.llm.scripted_llm import call_tool, say
from app.domain.errors import LLMError
from tests.conftest import ServiceFactory

READER = InMemoryMetricReader()


@pytest.fixture(scope="module", autouse=True)
def meter_provider() -> None:
    # The global provider can only be set once per process.
    metrics.set_meter_provider(MeterProvider(metric_readers=[READER]))


@pytest.fixture
def reader() -> Iterator[InMemoryMetricReader]:
    READER.get_metrics_data()  # values are cumulative: tests compare before and after
    yield READER


def total(reader: InMemoryMetricReader, name: str, **attributes: object) -> float:
    """Sum (counters) or count (histograms) of the points of a metric matching the attributes."""
    data = reader.get_metrics_data()
    if data is None:
        return 0.0
    points = [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
        if all((point.attributes or {}).get(key) == value for key, value in attributes.items())
    ]
    return float(sum(_amount(point) for point in points))


def _amount(point: object) -> float:
    if isinstance(point, HistogramDataPoint):
        return point.count
    return float(getattr(point, "value", 0))


async def test_a_run_is_counted_by_status_with_its_steps_and_duration(
    make_service: ServiceFactory, reader: InMemoryMetricReader
) -> None:
    before = total(reader, "agent.runs", **{"agent.status": "completed"})
    durations_before = total(reader, "agent.run.duration")

    await make_service([call_tool("calculator", operation="add", a=2, b=3), say("5")]).answer("?")

    assert total(reader, "agent.runs", **{"agent.status": "completed"}) == before + 1
    assert total(reader, "agent.run.duration") == durations_before + 1


async def test_tool_calls_are_counted_by_tool_and_outcome(
    make_service: ServiceFactory, reader: InMemoryMetricReader
) -> None:
    labels = {"gen_ai.tool.name": "calculator", "tool.is_error": True}
    before = total(reader, "agent.tool.calls", **labels)
    script = [call_tool("calculator", operation="divide", a=1, b=0), say("Cannot divide by zero")]

    await make_service(script).answer("1 / 0?")

    assert total(reader, "agent.tool.calls", **labels) == before + 1


async def test_token_usage_is_recorded_for_input_and_output(
    make_service: ServiceFactory, reader: InMemoryMetricReader
) -> None:
    before = total(reader, "gen_ai.client.token.usage", **{"gen_ai.token.type": "output"})

    await make_service([say("hi")]).answer("hello")

    after = total(reader, "gen_ai.client.token.usage", **{"gen_ai.token.type": "output"})
    assert after == before + 1


async def test_a_failed_run_is_counted_by_error_type(
    make_service: ServiceFactory, reader: InMemoryMetricReader
) -> None:
    before = total(reader, "agent.failures", **{"error.type": "LLMError"})

    with pytest.raises(LLMError):
        await make_service([LLMError("provider down")]).answer("hi")

    assert total(reader, "agent.failures", **{"error.type": "LLMError"}) == before + 1
