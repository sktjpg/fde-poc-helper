import asyncio

from pydantic import BaseModel

from app.agents.tools.base import Tool, ToolRegistry
from app.domain.models import ToolCall


def call(name: str = "calculator", **arguments: object) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=dict(arguments))


async def test_calculator_returns_structured_result(tools: ToolRegistry) -> None:
    output = await tools.execute(call(operation="multiply", a=6, b=7))

    assert not output.is_error
    assert output.content == '{"result":42.0}'


async def test_unknown_tool_is_an_error_output(tools: ToolRegistry) -> None:
    output = await tools.execute(call(name="delete_everything"))

    assert output.is_error
    assert "Unknown tool" in output.content


async def test_invalid_arguments_are_rejected_before_execution(tools: ToolRegistry) -> None:
    output = await tools.execute(call(operation="power", a="x", b=2))

    assert output.is_error
    assert "Invalid arguments" in output.content


async def test_domain_failure_is_reported_to_the_model(tools: ToolRegistry) -> None:
    output = await tools.execute(call(operation="divide", a=1, b=0))

    assert output.is_error
    assert output.content == "Cannot divide by zero"


class NoArgs(BaseModel):
    pass


async def test_slow_tool_times_out() -> None:
    async def slow(args: NoArgs) -> NoArgs:
        await asyncio.sleep(1)
        return args

    registry = ToolRegistry(
        [Tool(name="slow", description="", args_model=NoArgs, handler=slow)],
        timeout_seconds=0.01,
    )

    output = await registry.execute(call(name="slow"))

    assert output.is_error
    assert "timed out" in output.content


async def test_unexpected_crash_does_not_leak_internals() -> None:
    async def broken(args: NoArgs) -> NoArgs:
        raise RuntimeError("db password is hunter2")

    registry = ToolRegistry(
        [Tool(name="broken", description="", args_model=NoArgs, handler=broken)],
        timeout_seconds=1.0,
    )

    output = await registry.execute(call(name="broken"))

    assert output.is_error
    assert output.content == "Tool failed unexpectedly"


async def test_handler_timeout_is_not_reported_as_our_deadline() -> None:
    async def upstream_timeout(args: NoArgs) -> NoArgs:
        raise TimeoutError("socket timed out")

    registry = ToolRegistry(
        [Tool(name="flaky", description="", args_model=NoArgs, handler=upstream_timeout)],
        timeout_seconds=5.0,
    )

    output = await registry.execute(call(name="flaky"))

    assert output.is_error
    assert output.content == "Tool dependency timed out"


async def test_calculator_overflow_is_an_error_not_a_null(tools: ToolRegistry) -> None:
    output = await tools.execute(call(operation="multiply", a=1e308, b=10))

    assert output.is_error
    assert "too large" in output.content
