"""Anthropic adapter for the LLMClient port."""

from collections.abc import Sequence
from typing import Any

import anthropic

from app.domain.errors import LLMError
from app.domain.models import LLMResponse, Message, ToolCall, ToolSpec, Usage

# Lets the API re-run a policy-declined request on a fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
USABLE_STOP_REASONS = frozenset({"end_turn", "tool_use", "stop_sequence"})
RETRYABLE_STATUS_CODES = frozenset({408, 409})
MISSING_CREDENTIALS = "LLM credentials are not configured (set ANTHROPIC_API_KEY)"


class AnthropicLLM:
    def __init__(self, client: anthropic.AsyncAnthropic, *, model: str, max_tokens: int) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> LLMResponse:
        try:
            response = await self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[to_api_message(message) for message in messages],
                tools=[tool.model_dump() for tool in tools],  # type: ignore[misc]
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APITimeoutError as exc:
            raise LLMError("LLM request timed out", retryable=True) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("LLM rate limit reached", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code in RETRYABLE_STATUS_CODES
            raise LLMError(f"LLM request failed ({exc.status_code})", retryable=retryable) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the LLM provider", retryable=True) from exc
        except anthropic.AnthropicError as exc:
            # Anything else the SDK raises, e.g. a response it could not parse.
            raise LLMError("LLM provider returned an unusable response") from exc

        return from_api_response(response)


def to_api_message(message: Message) -> Any:
    if message.role == "tool":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": output.tool_call_id,
                    "content": output.content,
                    "is_error": output.is_error,
                }
                for output in message.tool_outputs
            ],
        }
    if message.role == "assistant":
        if message.provider_content is not None:
            return {"role": "assistant", "content": message.provider_content}
        text_blocks: list[dict[str, Any]] = (
            [{"type": "text", "text": message.text}] if message.text else []
        )
        tool_blocks: list[dict[str, Any]] = [
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            for call in message.tool_calls
        ]
        return {"role": "assistant", "content": [*text_blocks, *tool_blocks]}
    return {"role": "user", "content": message.text}


def from_api_response(response: Any) -> LLMResponse:
    # Check the stop reason before trusting the content.
    if response.stop_reason == "refusal":
        raise LLMError("The model declined the request")
    if response.stop_reason == "max_tokens":
        raise LLMError("The model response was truncated (max_tokens reached)")
    if response.stop_reason not in USABLE_STOP_REASONS:
        raise LLMError(f"Unexpected stop reason from the model: {response.stop_reason}")

    text = "".join(block.text for block in response.content if block.type == "text")
    tool_calls = tuple(
        ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
        for block in response.content
        if block.type == "tool_use"
    )
    return LLMResponse(
        message=Message(
            role="assistant",
            text=text,
            tool_calls=tool_calls,
            provider_content=response.content,
        ),
        usage=Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        ),
        model=response.model,
    )


def build_anthropic_llm(
    *, api_key: str | None, model: str, max_tokens: int, timeout_seconds: float
) -> AnthropicLLM:
    """Create the adapter, failing with a clear error when no credentials can be resolved."""
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)
    except anthropic.AnthropicError as exc:
        raise LLMError(MISSING_CREDENTIALS) from exc
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        # Otherwise the SDK raises a TypeError on the first request.
        raise LLMError(MISSING_CREDENTIALS)
    return AnthropicLLM(client, model=model, max_tokens=max_tokens)
