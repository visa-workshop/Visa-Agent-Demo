"""FastAPI application entry point for the Visa Disputes Processing Brain."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import router, set_brain
from src.instrumentation import init_sentry
from src.orchestrator.brain import DisputeBrain
from src.queue.task_queue import DisputeTaskQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize Sentry instrumentation (no-op if SENTRY_DSN is not set)
init_sentry()


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

app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "service": "Visa Disputes Processing Brain",
        "version": "0.1.0",
        "docs": "/docs",
    }
