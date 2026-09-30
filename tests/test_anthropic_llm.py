from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.llm.anthropic_llm import from_api_response, to_api_message
from app.domain.errors import LLMError
from app.domain.models import Message, ToolCall, ToolOutput


def api_response(content: list[Any], stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        model="claude-opus-5-5",
    )


def test_parses_text_and_tool_calls_and_keeps_raw_blocks() -> None:
    content = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="Let me check."),
        SimpleNamespace(type="tool_use", id="t1", name="calculator", input={"a": 1}),
    ]

    response = from_api_response(api_response(content, stop_reason="tool_use"))

    assert response.message.text == "Let me check."
    assert response.message.tool_calls == (
        ToolCall(id="t1", name="calculator", arguments={"a": 1}),
    )
    assert response.message.provider_content is content
    assert response.usage.input_tokens == 10


@pytest.mark.parametrize(
    "stop_reason", ["refusal", "max_tokens", "pause_turn", "model_context_window_exceeded"]
)
def test_unusable_stop_reasons_raise(stop_reason: str) -> None:
    with pytest.raises(LLMError):
        from_api_response(api_response([], stop_reason=stop_reason))


def test_assistant_turn_is_replayed_verbatim() -> None:
    raw = [SimpleNamespace(type="thinking", thinking="")]
    message = Message(role="assistant", text="ignored", provider_content=raw)

    assert to_api_message(message) == {"role": "assistant", "content": raw}


def test_tool_outputs_become_a_single_user_message() -> None:
    message = Message(
        role="tool",
        tool_outputs=(
            ToolOutput(tool_call_id="t1", content="5"),
            ToolOutput(tool_call_id="t2", content="boom", is_error=True),
        ),
    )

    api_message = to_api_message(message)

    assert api_message["role"] == "user"
    assert [block["tool_use_id"] for block in api_message["content"]] == ["t1", "t2"]
    assert api_message["content"][1]["is_error"] is True
