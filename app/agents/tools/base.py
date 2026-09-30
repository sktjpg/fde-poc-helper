"""Typed tools and the registry that validates, times out and executes them."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.errors import ToolError
from app.domain.models import ToolCall, ToolOutput, ToolSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool[ArgsT: BaseModel]:
    name: str
    description: str
    args_model: type[ArgsT]
    handler: Callable[[ArgsT], Awaitable[BaseModel]]

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.args_model.model_json_schema(),
        )


class ToolRegistry:
    """The only way the agent can act: every call is validated and bounded in time."""

    def __init__(self, tools: Iterable[Tool[Any]], *, timeout_seconds: float) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._timeout_seconds = timeout_seconds

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolOutput:
        """Run one tool call. Failures come back as error outputs so the model can react."""
        tool = self._tools.get(call.name)
        if tool is None:
            return _error(call, f"Unknown tool: {call.name}")

        try:
            args = tool.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            problems = json.dumps(exc.errors(include_url=False, include_input=False), default=str)
            return _error(call, f"Invalid arguments: {problems}")

        deadline = asyncio.timeout(self._timeout_seconds)
        try:
            async with deadline:
                result = await tool.handler(args)
        except TimeoutError:
            if deadline.expired():
                return _error(call, f"Tool timed out after {self._timeout_seconds}s")
            # The handler's own dependency timed out: an external failure, not our deadline.
            logger.warning("tool %s: upstream timeout", call.name)
            return _error(call, "Tool dependency timed out")
        except ToolError as exc:
            return _error(call, str(exc))
        except Exception:
            # Unexpected bug or infrastructure failure: keep the details in our logs,
            # give the model a safe message.
            logger.exception("tool %s crashed", call.name)
            return _error(call, "Tool failed unexpectedly")

        return ToolOutput(tool_call_id=call.id, content=result.model_dump_json())


def _error(call: ToolCall, message: str) -> ToolOutput:
    return ToolOutput(tool_call_id=call.id, content=message, is_error=True)
