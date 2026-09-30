"""Scripted LLM for tests and offline work: no network, fully deterministic."""

from collections.abc import Sequence

from app.domain.errors import LLMError
from app.domain.models import LLMResponse, Message, ToolCall, ToolSpec


class ScriptedLLM:
    def __init__(self, script: Sequence[LLMResponse | Exception]) -> None:
        self._script = tuple(script)
        self.calls: list[tuple[Message, ...]] = []

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> LLMResponse:
        turn = len(self.calls)
        self.calls.append(tuple(messages))
        if turn >= len(self._script):
            raise LLMError("ScriptedLLM ran out of scripted responses")
        step = self._script[turn]
        if isinstance(step, Exception):
            raise step
        return step


def say(text: str) -> LLMResponse:
    return LLMResponse(message=Message(role="assistant", text=text))


def call_tool(name: str, *, call_id: str = "call_1", **arguments: object) -> LLMResponse:
    tool_call = ToolCall(id=call_id, name=name, arguments=dict(arguments))
    return LLMResponse(message=Message(role="assistant", tool_calls=(tool_call,)))
