"""Ports: what the core needs from the outside world. Adapters implement them."""

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import LLMResponse, Message, ToolSpec


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> LLMResponse: ...
