from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.schemas import AgentRunRequest, ErrorResponse
from app.dependencies import get_agent_service
from app.domain.models import AgentResult
from app.services.agent_service import AgentService

CHAT_PAGE = Path(__file__).parent / "static" / "chat.html"

router = APIRouter()


@router.get("/", include_in_schema=False)
async def chat_page() -> FileResponse:
    """Demo page: a chat that calls /agent/run and shows each run's tool calls and cost."""
    return FileResponse(CHAT_PAGE, media_type="text/html")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/agent/run",
    response_model=AgentResult,
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def agent_run(
    body: AgentRunRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentResult:
    return await service.answer(body.input)
