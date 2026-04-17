"""FastAPI application entry point for the Visa Disputes Processing Brain."""

import logging
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.api.routes import router, set_brain
from src.orchestrator.brain import DisputeBrain
from src.queue.task_queue import DisputeTaskQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager - initializes and tears down the brain."""
    logger.info("Initializing Visa Disputes Processing Brain...")

    # Initialize the task queue and brain
    task_queue = DisputeTaskQueue()
    brain = DisputeBrain(task_queue)

    # Start the brain's worker loops
    await brain.start()

    # Make the brain available to API routes
    set_brain(brain)

    logger.info("Brain is online and ready to process disputes")
    yield

    # Shutdown
    logger.info("Shutting down brain...")
    await brain.stop()
    logger.info("Brain shutdown complete")


app = FastAPI(
    title="Visa Disputes Processing Brain",
    description=(
        "Autonomous AI agent system for processing Visa disputes according to "
        "Visa Core Rules and Product/Service Rules. The Brain picks dispute tasks "
        "from a queue and processes them through specialized sub-agents that encode "
        "Visa's dispute processing rules."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# 2.1 — CORS middleware with configurable origins
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
_cors_origins = [o.strip() for o in _cors_origins if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 2.2 — Request ID middleware
class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns a unique X-Request-ID to every request/response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIDMiddleware)


# 2.4 — Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a structured JSON error."""
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request_id,
        },
    )


app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "service": "Visa Disputes Processing Brain",
        "version": "0.1.0",
        "docs": "/docs",
    }
