"""FastAPI entry point: wires the router and maps domain errors to HTTP responses."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings
from app.domain.errors import InputRejectedError, LLMError
from app.observability.otel import configure_tracing
from app.observability.tracer import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    provider = configure_tracing(get_settings())
    yield
    if provider is not None:
        provider.shutdown()  # flush spans still in the batch queue


def create_app() -> FastAPI:
    application = FastAPI(title="Agent API", lifespan=lifespan)
    application.include_router(router)

    @application.exception_handler(RequestValidationError)
    async def handle_invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Same error shape as every other failure, without echoing the rejected input.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return JSONResponse(status_code=422, content={"error": f"Invalid request: {problems}"})

    @application.exception_handler(InputRejectedError)
    async def handle_input_rejected(request: Request, exc: InputRejectedError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    @application.exception_handler(LLMError)
    async def handle_llm_error(request: Request, exc: LLMError) -> JSONResponse:
        logger.warning("llm error on %s: %s", request.url.path, exc)
        status_code = 503 if exc.retryable else 502
        return JSONResponse(status_code=status_code, content={"error": str(exc)})

    return application


app = create_app()
