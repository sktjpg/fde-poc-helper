import pytest

from app.adapters.llm.scripted_llm import ScriptedLLM, call_tool, say
from app.agents.loop import run_agent
from app.agents.tools.base import ToolRegistry
from app.domain.errors import LLMError
from app.domain.models import AgentResult, LLMResponse, Message, Usage
from app.prompts.registry import get_prompt

PROMPT = get_prompt("agent_system")


async def run(llm: ScriptedLLM, tools: ToolRegistry, max_steps: int = 4) -> AgentResult:
    return await run_agent("question", llm=llm, tools=tools, prompt=PROMPT, max_steps=max_steps)


async def test_answers_directly_when_no_tool_is_needed(tools: ToolRegistry) -> None:
    result = await run(ScriptedLLM([say("hello")]), tools)

    assert result.status == "completed"
    assert result.answer == "hello"
    assert result.steps == 1
    assert result.tool_calls == ()
    assert result.prompt_version == "agent_system@v1"


async def test_feeds_tool_result_back_to_the_model(tools: ToolRegistry) -> None:
    llm = ScriptedLLM([call_tool("calculator", operation="add", a=2, b=3), say("It is 5")])

    result = await run(llm, tools)

    assert result.status == "completed"
    assert result.answer == "It is 5"
    assert [record.name for record in result.tool_calls] == ["calculator"]
    tool_message = llm.calls[1][-1]
    assert tool_message.role == "tool"
    assert tool_message.tool_outputs[0].content == '{"result":5.0}'


async def test_tool_error_is_returned_to_the_model_not_raised(tools: ToolRegistry) -> None:
    llm = ScriptedLLM(
        [call_tool("calculator", operation="divide", a=1, b=0), say("Cannot divide by zero")]
    )

    result = await run(llm, tools)

    assert result.status == "completed"
    assert result.tool_calls[0].is_error
    assert llm.calls[1][-1].tool_outputs[0].is_error


async def test_stops_at_max_steps(tools: ToolRegistry) -> None:
    script = [call_tool("calculator", operation="add", a=n, b=1) for n in range(10)]

    result = await run(ScriptedLLM(script), tools, max_steps=3)

    assert result.status == "max_steps"
    assert result.steps == 3
    # On the last step no model call is left to read results, so those tools never run.
    assert len(result.tool_calls) == 2


async def test_stops_when_the_same_tool_call_repeats(tools: ToolRegistry) -> None:
    repeated = call_tool("calculator", operation="add", a=1, b=1)

    result = await run(ScriptedLLM([repeated, repeated, repeated]), tools, max_steps=10)

    assert result.status == "stalled"
    assert result.steps == 2
    assert len(result.tool_calls) == 1


async def test_a_failed_tool_call_may_be_retried(tools: ToolRegistry) -> None:
    failing = call_tool("calculator", operation="divide", a=1, b=0)

    result = await run(ScriptedLLM([failing, failing, say("Cannot be done")]), tools)

    assert result.status == "completed"
    assert [record.is_error for record in result.tool_calls] == [True, True]


async def test_llm_failure_propagates(tools: ToolRegistry) -> None:
    llm = ScriptedLLM([LLMError("LLM request timed out", retryable=True)])

    with pytest.raises(LLMError):
        await run(llm, tools)


async def test_accumulates_usage_and_cost(tools: ToolRegistry) -> None:
    priced = Usage(input_tokens=1_000_000, output_tokens=100_000)
    first = call_tool("calculator", operation="add", a=1, b=2).model_copy(
        update={"usage": priced, "model": "claude-opus-5-5"}
    )
    last = LLMResponse(
        message=Message(role="assistant", text="3"), usage=priced, model="claude-opus-5-5"
    )

    result = await run(ScriptedLLM([first, last]), tools)

    assert result.usage == Usage(input_tokens=2_000_000, output_tokens=200_000)
    assert result.cost_usd == 12.0


async def test_cost_is_unknown_when_the_model_has_no_price(tools: ToolRegistry) -> None:
    result = await run(ScriptedLLM([say("hi")]), tools)

    assert result.cost_usd is None
