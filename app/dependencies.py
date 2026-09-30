"""Composition root: the one place where ports are bound to concrete adapters."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.adapters.llm.anthropic_llm import build_anthropic_llm
from app.adapters.llm.claude_code_llm import ClaudeCodeLLM
from app.agents.tools.base import ToolRegistry
from app.agents.tools.calculator import calculator
from app.config import Settings, get_settings
from app.domain.ports import LLMClient
from app.services.agent_service import AgentService


@lru_cache
def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "claude_code":
        return ClaudeCodeLLM(model=settings.llm_model, timeout_seconds=settings.llm_timeout_seconds)
    api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    return build_anthropic_llm(
        api_key=api_key,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def get_tools(settings: Annotated[Settings, Depends(get_settings)]) -> ToolRegistry:
    return ToolRegistry([calculator], timeout_seconds=settings.tool_timeout_seconds)


def get_agent_service(
    llm: Annotated[LLMClient, Depends(get_llm)],
    tools: Annotated[ToolRegistry, Depends(get_tools)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentService:
    return AgentService(
        llm=llm,
        tools=tools,
        max_steps=settings.agent_max_steps,
        max_input_chars=settings.max_input_chars,
    )
