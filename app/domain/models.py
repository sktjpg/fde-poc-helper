"""Provider-neutral data contracts shared by every layer."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ToolSpec(Frozen):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(Frozen):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolOutput(Frozen):
    tool_call_id: str
    content: str
    is_error: bool = False


class Usage(Frozen):
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class Message(Frozen):
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_outputs: tuple[ToolOutput, ...] = ()
    # Raw provider blocks of an assistant turn. Replayed verbatim on the next request so
    # provider-specific content (e.g. thinking blocks) survives the round trip.
    provider_content: Any = Field(default=None, exclude=True, repr=False)


class LLMResponse(Frozen):
    message: Message
    usage: Usage = Usage()
    model: str = ""


AgentStatus = Literal["completed", "max_steps", "stalled"]


class ToolCallRecord(Frozen):
    step: int
    name: str
    arguments: dict[str, Any]
    is_error: bool
    latency_ms: float


class AgentResult(Frozen):
    trace_id: str
    status: AgentStatus
    answer: str
    steps: int
    prompt_version: str
    tool_calls: tuple[ToolCallRecord, ...] = ()
    usage: Usage = Usage()
    cost_usd: float | None = None
