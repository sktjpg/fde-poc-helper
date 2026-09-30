from pydantic import BaseModel, ConfigDict, Field

# Hard ceiling on the request body field; the configurable limit is enforced by the input guard.
MAX_INPUT_LENGTH = 100_000


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    input: str = Field(min_length=1, max_length=MAX_INPUT_LENGTH)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    error: str
