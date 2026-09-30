"""Use case: answer a user request with the agent, behind the input and output guards."""

from dataclasses import dataclass

from app.agents.loop import run_agent
from app.agents.tools.base import ToolRegistry
from app.domain.models import AgentResult
from app.domain.ports import LLMClient
from app.prompts.registry import get_prompt
from app.security.input_guard import check_input
from app.security.output_filter import filter_output, mask_secrets

AGENT_PROMPT_NAME = "agent_system"


@dataclass(frozen=True)
class AgentService:
    llm: LLMClient
    tools: ToolRegistry
    max_steps: int
    max_input_chars: int

    async def answer(self, user_input: str) -> AgentResult:
        cleaned = check_input(user_input, max_chars=self.max_input_chars)
        result = await run_agent(
            cleaned,
            llm=self.llm,
            tools=self.tools,
            prompt=get_prompt(AGENT_PROMPT_NAME),
            max_steps=self.max_steps,
        )
        # Everything that leaves the system is masked, including echoed tool arguments.
        tool_calls = tuple(
            record.model_copy(update={"arguments": mask_secrets(record.arguments)})
            for record in result.tool_calls
        )
        return result.model_copy(
            update={"answer": filter_output(result.answer), "tool_calls": tool_calls}
        )
