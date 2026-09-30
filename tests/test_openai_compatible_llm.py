import json

import httpx
import pytest
import respx

from app.adapters.llm.openai_compatible_llm import OpenAICompatibleLLM
from app.domain.errors import LLMError
from app.domain.models import Message, ToolCall, ToolOutput, ToolSpec
from app.observability.cost_tracker import ModelPrice

BASE_URL = "http://llm.test/v1"
URL = f"{BASE_URL}/chat/completions"
CALCULATOR = ToolSpec(name="calculator", description="Arithmetic", input_schema={"type": "object"})


def make_llm(price: ModelPrice | None = None, api_key: str | None = None) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        base_url=f"{BASE_URL}/",
        model="local-model",
        max_tokens=256,
        timeout_seconds=1.0,
        api_key=api_key,
        price=price,
    )


def completion(message: dict[str, object], finish_reason: str = "stop") -> dict[str, object]:
    return {
        "model": "local-model",
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
    }


def tool_call_message(arguments: str) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "calculator", "arguments": arguments},
            }
        ],
    }


async def ask(llm: OpenAICompatibleLLM) -> object:
    return await llm.complete(system="sys", messages=[Message(role="user", text="hi")], tools=[])


@respx.mock
async def test_a_text_answer_is_parsed_with_usage_and_model() -> None:
    respx.post(URL).respond(json=completion({"role": "assistant", "content": "Hello"}))

    response = await make_llm().complete(
        system="sys", messages=[Message(role="user", text="hi")], tools=[]
    )

    assert response.message.text == "Hello"
    assert response.message.tool_calls == ()
    assert (response.usage.input_tokens, response.usage.output_tokens) == (1000, 500)
    assert response.model == "local-model"
    assert response.cost_usd is None


@respx.mock
async def test_a_tool_call_is_parsed_into_arguments() -> None:
    message = tool_call_message('{"operation": "add", "a": 2, "b": 3}')
    respx.post(URL).respond(json=completion(message, finish_reason="tool_calls"))

    response = await make_llm().complete(
        system="sys", messages=[Message(role="user", text="2 + 3?")], tools=[CALCULATOR]
    )

    assert response.message.tool_calls == (
        ToolCall(id="c1", name="calculator", arguments={"operation": "add", "a": 2, "b": 3}),
    )


@respx.mock
async def test_the_request_carries_the_conversation_and_the_tools() -> None:
    route = respx.post(URL).respond(json=completion({"role": "assistant", "content": "5"}))
    call = ToolCall(id="c1", name="calculator", arguments={"a": 2})
    messages = [
        Message(role="user", text="2 + 3?"),
        Message(role="assistant", tool_calls=(call,)),
        Message(role="tool", tool_outputs=(ToolOutput(tool_call_id="c1", content="5"),)),
    ]

    await make_llm(api_key="k").complete(system="sys", messages=messages, tools=[CALCULATOR])

    request = route.calls.last.request
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer k"
    assert body["model"] == "local-model"
    assert [message["role"] for message in body["messages"]] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert body["messages"][2]["tool_calls"][0]["function"] == {
        "name": "calculator",
        "arguments": '{"a": 2}',
    }
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "5"}
    assert body["tools"][0]["function"]["name"] == "calculator"


@respx.mock
async def test_a_configured_price_becomes_the_cost_of_the_call() -> None:
    respx.post(URL).respond(json=completion({"role": "assistant", "content": "Hello"}))
    llm = make_llm(price=ModelPrice(input_per_mtok=1.0, output_per_mtok=2.0))

    response = await llm.complete(
        system="sys", messages=[Message(role="user", text="hi")], tools=[]
    )

    assert response.cost_usd == 0.002


@respx.mock
async def test_a_timeout_is_a_retryable_error() -> None:
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(LLMError) as raised:
        await ask(make_llm())

    assert raised.value.retryable


@respx.mock
async def test_an_unreachable_server_is_a_retryable_error() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(LLMError) as raised:
        await ask(make_llm())

    assert raised.value.retryable
    assert "reach" in str(raised.value)


@pytest.mark.parametrize(("status", "retryable"), [(500, True), (429, True), (400, False)])
@respx.mock
async def test_http_errors_map_to_llm_errors(status: int, retryable: bool) -> None:
    respx.post(URL).respond(status_code=status, json={"error": "secret detail"})

    with pytest.raises(LLMError) as raised:
        await ask(make_llm())

    assert raised.value.retryable is retryable
    assert str(raised.value) == f"LLM request failed ({status})"


@pytest.mark.parametrize("body", [b"not json", b'{"choices": []}', b'{"unexpected": true}'])
@respx.mock
async def test_a_malformed_response_is_rejected(body: bytes) -> None:
    respx.post(URL).respond(content=body)

    with pytest.raises(LLMError, match="unusable"):
        await ask(make_llm())


@pytest.mark.parametrize("arguments", ["{not json", "[1, 2]"])
@respx.mock
async def test_invalid_tool_arguments_from_the_model_are_rejected(arguments: str) -> None:
    respx.post(URL).respond(json=completion(tool_call_message(arguments), "tool_calls"))

    with pytest.raises(LLMError, match="tool arguments"):
        await ask(make_llm())


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
@respx.mock
async def test_unusable_finish_reasons_raise(finish_reason: str) -> None:
    message: dict[str, object] = {"role": "assistant", "content": "partial"}
    respx.post(URL).respond(json=completion(message, finish_reason))

    with pytest.raises(LLMError):
        await ask(make_llm())
