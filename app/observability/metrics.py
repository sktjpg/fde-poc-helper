"""Agent metrics through the OpenTelemetry API.

The instruments are no-ops until a MeterProvider is configured (see otel.py), so the code
is always instrumented. Attributes are low-cardinality on purpose (status, model, tool
name, error type): never put user input or ids in a metric attribute.
"""

from opentelemetry import metrics

from app.domain.models import Usage

_meter = metrics.get_meter("app")

_runs = _meter.create_counter(
    "agent.runs", unit="{run}", description="Agent runs that finished, by final status"
)
_failures = _meter.create_counter(
    "agent.failures", unit="{run}", description="Agent runs that raised, by error type"
)
_run_duration = _meter.create_histogram(
    "agent.run.duration", unit="s", description="Wall time of an agent run"
)
_run_steps = _meter.create_histogram(
    "agent.run.steps", unit="{step}", description="Model calls per agent run"
)
_cost = _meter.create_counter(
    "agent.cost", unit="USD", description="Cost of model calls whose price is known"
)
# Names and units from the OpenTelemetry semantic conventions for generative AI clients.
_token_usage = _meter.create_histogram(
    "gen_ai.client.token.usage", unit="{token}", description="Tokens per model call"
)
_llm_duration = _meter.create_histogram(
    "gen_ai.client.operation.duration", unit="s", description="Duration of a model call"
)
_tool_calls = _meter.create_counter(
    "agent.tool.calls", unit="{call}", description="Tool executions, by tool and outcome"
)
_tool_duration = _meter.create_histogram(
    "agent.tool.duration", unit="s", description="Duration of a tool execution"
)


def record_run(*, status: str, steps: int, duration_s: float) -> None:
    attributes = {"agent.status": status}
    _runs.add(1, attributes)
    _run_duration.record(duration_s, attributes)
    _run_steps.record(steps, attributes)


def record_run_failure(*, error: str) -> None:
    _failures.add(1, {"error.type": error})


def record_llm_call(*, model: str, usage: Usage, cost_usd: float | None, duration_s: float) -> None:
    model_attributes = {"gen_ai.operation.name": "chat", "gen_ai.response.model": model}
    _llm_duration.record(duration_s, model_attributes)
    _token_usage.record(usage.input_tokens, {**model_attributes, "gen_ai.token.type": "input"})
    _token_usage.record(usage.output_tokens, {**model_attributes, "gen_ai.token.type": "output"})
    if cost_usd is not None:
        _cost.add(cost_usd, {"gen_ai.response.model": model})


def record_tool_call(*, name: str, is_error: bool, duration_s: float) -> None:
    attributes = {"gen_ai.tool.name": name, "tool.is_error": is_error}
    _tool_calls.add(1, attributes)
    _tool_duration.record(duration_s, attributes)
