"""Adapter for any server that speaks the OpenAI chat-completions API.

That covers local models (Ollama, vLLM, LM Studio, llama.cpp) and hosted gateways, so the
agent can run on a self-hosted model by changing configuration only.
"""

import json
from collections.abc import Sequence
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.domain.errors import LLMError
from app.domain.models import LLMResponse, Message, ToolCall, ToolSpec, Usage
from app.observability.cost_tracker import ModelPrice, cost_usd

CHAT_COMPLETIONS_PATH = "/chat/completions"
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})
UNUSABLE_RESPONSE = "LLM provider returned an unusable response"


class _Function(BaseModel):
    name: str
    arguments: str


class _ToolCall(BaseModel):
    id: str
    function: _Function


class _Message(BaseModel):
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None


class _Choice(BaseModel):
    message: _Message
    finish_reason: str | None = None


class _Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _Completion(BaseModel):
    """The part of the response body this adapter relies on."""

    choices: list[_Choice]
    usage: _Usage = _Usage()
    model: str = ""


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        max_tokens: int,
        timeout_seconds: float,
        api_key: str | None = None,
        price: ModelPrice | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}{CHAT_COMPLETIONS_PATH}"
        self._model = model
        self._max_tokens = max_tokens
        self._timeout_seconds = timeout_seconds
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._price = price

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system},
                *(item for message in messages for item in to_api_messages(message)),
            ],
        }
        if tools:
            body["tools"] = [to_api_tool(tool) for tool in tools]

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(self._url, json=body, headers=self._headers)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMError("LLM request timed out", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status >= 500 or status in RETRYABLE_STATUS_CODES
            raise LLMError(f"LLM request failed ({status})", retryable=retryable) from exc
        except httpx.TransportError as exc:
            raise LLMError("Could not reach the LLM provider", retryable=True) from exc

        parsed = from_api_response(response.content)
        if self._price is None:
            return parsed
        return parsed.model_copy(update={"cost_usd": cost_usd(self._price, parsed.usage)})


def to_api_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def to_api_messages(message: Message) -> list[dict[str, Any]]:
    """One of our messages as API messages: every tool result is a message of its own."""
    if message.role == "tool":
        return [
            {"role": "tool", "tool_call_id": output.tool_call_id, "content": output.content}
            for output in message.tool_outputs
        ]
    if message.role == "assistant":
        assistant: dict[str, Any] = {"role": "assistant", "content": message.text or None}
        if message.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ]
        return [assistant]
    role: Literal["user"] = "user"
    return [{"role": role, "content": message.text}]


def from_api_response(raw: bytes) -> LLMResponse:
    try:
        completion = _Completion.model_validate_json(raw)
    except ValidationError as exc:
        raise LLMError(UNUSABLE_RESPONSE) from exc
    if not completion.choices:
        raise LLMError(UNUSABLE_RESPONSE)

    choice = completion.choices[0]
    # Check why the model stopped before trusting the content.
    if choice.finish_reason == "length":
        raise LLMError("The model response was truncated (max_tokens reached)")
    if choice.finish_reason == "content_filter":
        raise LLMError("The model declined the request")

    return LLMResponse(
        message=Message(
            role="assistant",
            text=choice.message.content or "",
            tool_calls=tuple(_to_tool_call(call) for call in choice.message.tool_calls or ()),
        ),
        usage=Usage(
            input_tokens=completion.usage.prompt_tokens,
            output_tokens=completion.usage.completion_tokens,
        ),
        model=completion.model,
    )


def _to_tool_call(call: _ToolCall) -> ToolCall:
    # The arguments arrive as a JSON string written by the model: never assume it is valid.
    try:
        arguments = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError as exc:
        raise LLMError("The model produced tool arguments that are not valid JSON") from exc
    if not isinstance(arguments, dict):
        raise LLMError("The model produced tool arguments that are not an object")
    return ToolCall(id=call.id, name=call.function.name, arguments=arguments)
