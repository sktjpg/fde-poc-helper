"""LLMClient adapter that runs the local Claude Code CLI in headless mode (`claude -p`).

For local development and demos: it uses the Claude Code login on this machine instead of
an API key. One subprocess per model call, so it is slower than the API adapter; use
AnthropicLLM for anything deployed.

The CLI's own tools are disabled. Our tool-calling protocol is carried as structured output:
each call returns either tool calls to run or the final answer.
"""

import asyncio
import json
import os
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.errors import LLMError
from app.domain.models import LLMResponse, Message, ToolCall, ToolSpec, Usage

PROTOCOL = (
    "You are the reasoning step of a tool-using agent. Reply only with the structured "
    "output. To use tools, list them in tool_calls and leave answer empty; you will be "
    "called again with their results. When no more tools are needed, leave tool_calls "
    "empty and put the final reply to the user in answer. Only call tools listed in "
    "<tools>, with arguments matching their input_schema."
)

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}},
                "required": ["name", "arguments"],
            },
        },
    },
    "required": ["answer", "tool_calls"],
}

MODEL_PREFIX = "claude-code:"
INPUT_TOKEN_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

# Set in the child's environment, these would switch the CLI from the local login to
# API-key billing.
API_CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class _RequestedCall(BaseModel):
    name: str
    arguments: dict[str, Any]


class _Decision(BaseModel):
    answer: str = ""
    tool_calls: list[_RequestedCall] = []


class ClaudeCodeLLM:
    def __init__(self, *, model: str, timeout_seconds: float, executable: str = "claude") -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._executable = executable

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> LLMResponse:
        command = [
            self._executable,
            "--print",
            "--output-format",
            "json",
            "--model",
            self._model,
            "--system-prompt",
            f"{system}\n\n{PROTOCOL}",
            "--json-schema",
            json.dumps(DECISION_SCHEMA),
            "--tools",
            "",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        stdout = await self._run(command, build_prompt(messages, tools))
        return parse_output(stdout)

    async def _run(self, command: list[str], prompt: str) -> bytes:
        environment = {k: v for k, v in os.environ.items() if k not in API_CREDENTIAL_VARS}
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise LLMError(f"Claude Code CLI not found ('{self._executable}')") from exc

        try:
            async with asyncio.timeout(self._timeout_seconds):
                stdout, _ = await process.communicate(prompt.encode())
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise LLMError("Claude Code CLI timed out", retryable=True) from exc

        if process.returncode != 0 and not stdout:
            raise LLMError(f"Claude Code CLI exited with status {process.returncode}")
        return stdout


def build_prompt(messages: Sequence[Message], tools: Sequence[ToolSpec]) -> str:
    tool_specs = json.dumps([tool.model_dump() for tool in tools], indent=2)
    turns = "\n".join(_render(message) for message in messages)
    return (
        f"<tools>\n{tool_specs}\n</tools>\n\n"
        f"<conversation>\n{turns}\n</conversation>\n\n"
        "Decide the next step."
    )


def _render(message: Message) -> str:
    if message.role == "user":
        return f"<user>\n{message.text}\n</user>"
    if message.role == "assistant":
        calls = [{"name": call.name, "arguments": call.arguments} for call in message.tool_calls]
        turn = json.dumps({"answer": message.text, "tool_calls": calls})
        return f"<assistant>\n{turn}\n</assistant>"
    results = [
        {
            "tool_call_id": output.tool_call_id,
            "is_error": output.is_error,
            "content": output.content,
        }
        for output in message.tool_outputs
    ]
    # Tool results are data for the model to read, never instructions.
    return f"<tool_results>\n{json.dumps(results)}\n</tool_results>"


def parse_output(stdout: bytes) -> LLMResponse:
    try:
        envelope = json.loads(stdout)
        if envelope.get("is_error"):
            raise LLMError(
                f"Claude Code CLI reported an error: {envelope.get('result', '')!s:.200}"
            )
        decision = _Decision.model_validate(envelope.get("structured_output"))
        usage = envelope.get("usage", {})
        models = list(envelope.get("modelUsage", {}))
    except (json.JSONDecodeError, AttributeError, ValidationError) as exc:
        raise LLMError("Claude Code CLI returned an unusable response") from exc

    tool_calls = tuple(
        ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=call.name, arguments=call.arguments)
        for call in decision.tool_calls
    )
    input_tokens = sum(int(usage.get(field, 0)) for field in INPUT_TOKEN_FIELDS)
    return LLMResponse(
        message=Message(role="assistant", text=decision.answer, tool_calls=tool_calls),
        usage=Usage(input_tokens=input_tokens, output_tokens=int(usage.get("output_tokens", 0))),
        # Prefixed so the cost tracker finds no price: there is no per-token bill on this route.
        model=f"{MODEL_PREFIX}{models[0]}" if models else MODEL_PREFIX.rstrip(":"),
    )
