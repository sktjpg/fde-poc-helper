import os
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from app.adapters.llm.scripted_llm import ScriptedLLM
from app.agents.tools.base import ToolRegistry
from app.agents.tools.calculator import calculator
from app.domain.models import LLMResponse
from app.services.agent_service import AgentService

ServiceFactory = Callable[[Sequence[LLMResponse | Exception]], AgentService]


HOST_ENV_PREFIXES = ("ANTHROPIC_", "LANGFUSE_", "OTLP_", "OTEL_", "LLM_", "AGENT_")


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests must not depend on, or use, credentials and settings from the host machine."""
    for name in list(os.environ):
        if name.startswith(HOST_ENV_PREFIXES):
            monkeypatch.delenv(name)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))


@pytest.fixture
def tools() -> ToolRegistry:
    return ToolRegistry([calculator], timeout_seconds=1.0)


@pytest.fixture
def make_service(tools: ToolRegistry) -> ServiceFactory:
    def factory(script: Sequence[LLMResponse | Exception]) -> AgentService:
        return AgentService(llm=ScriptedLLM(script), tools=tools, max_steps=4, max_input_chars=200)

    return factory
