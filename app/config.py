from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment (and .env in development)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    service_name: str = "agent-api"

    # "anthropic": the API, needs ANTHROPIC_API_KEY. "claude_code": the local Claude Code CLI
    # in headless mode, which uses this machine's Claude Code login (development and demos).
    llm_provider: Literal["anthropic", "claude_code"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_max_tokens: int = Field(default=16000, gt=0)
    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    agent_max_steps: int = Field(default=8, gt=0, le=50)
    tool_timeout_seconds: float = Field(default=10.0, gt=0)
    max_input_chars: int = Field(default=4000, gt=0)

    # Tracing is off unless one of these is set. Langfuse takes precedence.
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    otlp_endpoint: str | None = None
    otlp_headers: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
