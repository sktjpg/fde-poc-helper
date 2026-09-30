import json
import stat
import sys
from pathlib import Path

import pytest

from app.adapters.llm.claude_code_llm import ClaudeCodeLLM, build_prompt, parse_output
from app.domain.errors import LLMError
from app.domain.models import Message, ToolCall, ToolOutput, ToolSpec

TOOL = ToolSpec(name="calculator", description="maths", input_schema={"type": "object"})
QUESTION = (Message(role="user", text="2 + 3?"),)


def envelope(structured: object, **extra: object) -> bytes:
    payload = {
        "is_error": False,
        "structured_output": structured,
        "usage": {"input_tokens": 2, "cache_read_input_tokens": 10, "output_tokens": 4},
        "modelUsage": {"some-model": {}},
        **extra,
    }
    return json.dumps(payload).encode()


def fake_cli(tmp_path: Path, body: str) -> str:
    """An executable standing in for the CLI: reads stdin, then runs `body`."""
    script = tmp_path / "fake-claude"
    script.write_text(f"#!{sys.executable}\nimport sys, time\nsys.stdin.read()\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_prompt_contains_tools_and_every_turn_in_order() -> None:
    call = ToolCall(id="c1", name="calculator", arguments={"a": 2, "b": 3})
    messages = (
        *QUESTION,
        Message(role="assistant", tool_calls=(call,)),
        Message(role="tool", tool_outputs=(ToolOutput(tool_call_id="c1", content="5"),)),
    )

    prompt = build_prompt(messages, [TOOL])

    assert '"name": "calculator"' in prompt
    positions = [prompt.index(tag) for tag in ("<user>", "<assistant>", "<tool_results>")]
    assert positions == sorted(positions)
    assert '"content": "5"' in prompt


def test_parses_a_tool_call_decision() -> None:
    structured = {"answer": "", "tool_calls": [{"name": "calculator", "arguments": {"a": 2}}]}

    response = parse_output(envelope(structured))

    (call,) = response.message.tool_calls
    assert (call.name, call.arguments) == ("calculator", {"a": 2})
    assert call.id.startswith("call_")
    assert response.usage.input_tokens == 12
    assert response.model == "claude-code:some-model"


def test_parses_a_final_answer() -> None:
    response = parse_output(envelope({"answer": "It is 5", "tool_calls": []}))

    assert response.message.text == "It is 5"
    assert response.message.tool_calls == ()


@pytest.mark.parametrize(
    "stdout",
    [
        b"not json",
        b"[]",
        envelope(None),
        envelope({"answer": "x", "tool_calls": "nope"}),
        envelope({"answer": "x", "tool_calls": []}, is_error=True, result="quota exceeded"),
    ],
)
def test_unusable_output_raises(stdout: bytes) -> None:
    with pytest.raises(LLMError):
        parse_output(stdout)


async def test_runs_the_cli_and_returns_its_decision(tmp_path: Path) -> None:
    output = envelope({"answer": "It is 5", "tool_calls": []}).decode()
    cli = fake_cli(tmp_path, f"print({output!r})")
    llm = ClaudeCodeLLM(model="any", timeout_seconds=10, executable=cli)

    response = await llm.complete(system="Be precise.", messages=QUESTION, tools=[TOOL])

    assert response.message.text == "It is 5"


async def test_api_credentials_are_not_passed_to_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    body = (
        "import json, os\n"
        "leaked = 'ANTHROPIC_API_KEY' in os.environ\n"
        "print(json.dumps({'structured_output': {'answer': str(leaked), 'tool_calls': []}}))"
    )
    llm = ClaudeCodeLLM(model="any", timeout_seconds=10, executable=fake_cli(tmp_path, body))

    response = await llm.complete(system="", messages=QUESTION, tools=[])

    assert response.message.text == "False"


async def test_slow_cli_times_out(tmp_path: Path) -> None:
    llm = ClaudeCodeLLM(
        model="any", timeout_seconds=0.2, executable=fake_cli(tmp_path, "time.sleep(30)")
    )

    with pytest.raises(LLMError) as raised:
        await llm.complete(system="", messages=QUESTION, tools=[])

    assert raised.value.retryable


async def test_missing_cli_is_a_clear_error() -> None:
    llm = ClaudeCodeLLM(model="any", timeout_seconds=1, executable="/nonexistent/claude")

    with pytest.raises(LLMError, match="not found"):
        await llm.complete(system="", messages=QUESTION, tools=[])


async def test_failed_cli_without_output_raises(tmp_path: Path) -> None:
    llm = ClaudeCodeLLM(
        model="any", timeout_seconds=10, executable=fake_cli(tmp_path, "sys.exit(3)")
    )

    with pytest.raises(LLMError, match="status 3"):
        await llm.complete(system="", messages=QUESTION, tools=[])
