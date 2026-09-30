"""Composition root: the one place where ports are bound to concrete adapters."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.adapters.llm.anthropic_llm import build_anthropic_llm
from app.adapters.llm.claude_code_llm import ClaudeCodeLLM
from app.adapters.llm.openai_compatible_llm import OpenAICompatibleLLM
from app.agents.tools.base import ToolRegistry
from app.agents.tools.calculator import calculator
from app.config import Settings, get_settings
from app.domain.errors import LLMError
from app.domain.ports import LLMClient
from app.observability.cost_tracker import ModelPrice
from app.services.agent_service import AgentService

MISSING_BASE_URL = "LLM credentials are not configured (set LLM_BASE_URL)"


@lru_cache
def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "claude_code":
        return ClaudeCodeLLM(model=settings.llm_model, timeout_seconds=settings.llm_timeout_seconds)
    if settings.llm_provider == "openai_compatible":
        return _openai_compatible_llm(settings)
    api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    return build_anthropic_llm(
        api_key=api_key,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _openai_compatible_llm(settings: Settings) -> OpenAICompatibleLLM:
    if not settings.llm_base_url:
        raise LLMError(MISSING_BASE_URL)
    return OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
        price=_configured_price(settings),
    )


def _configured_price(settings: Settings) -> ModelPrice | None:
    # Both prices or none: half a price would report a wrong cost.
    input_price = settings.llm_input_price_per_mtok
    output_price = settings.llm_output_price_per_mtok
    if input_price is None or output_price is None:
        return None
    return ModelPrice(input_price, output_price)


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
