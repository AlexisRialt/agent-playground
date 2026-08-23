"""FastAPI application wiring.

Builds the app: shared clients and job store in the lifespan handler, routes
mounted from `app.api`. The endpoints themselves live in `app/api/`, and job
execution lives in `app/runner.py`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from anthropic import AsyncAnthropic
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger as log

from app.api import health_router, jobs_router
from app.config import settings
from app.db import create_pool
from app.jobs import JobStore, PostgresJobStore
from app.logs import setup_logging

setup_logging(settings.log_level)


async def open_job_store() -> JobStore:
    """Connect the durable job store.

    Split out of the lifespan so the tests can swap in `InMemoryJobStore` and
    stay off the network.
    """
    return PostgresJobStore(await create_pool(settings.database_url))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Shared clients live for the process lifetime.
    app.state.anthropic = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env
    app.state.http = httpx.AsyncClient()
    app.state.jobs = await open_job_store()
    app.state.tasks = set()  # keep strong refs so background tasks aren't GC'd
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    log.info(
        "startup: model={} effort={} max_iterations={} max_tokens={} workspace={} search={}",
        settings.model,
        settings.effort,
        settings.max_iterations,
        settings.max_tokens,
        settings.workspace_root,
        "enabled" if settings.serper_api_key else "stubbed (no SERPER_API_KEY)",
    )
    try:
        yield
    finally:
        log.info(
            "shutdown: closing clients ({} job task(s) in flight)", len(app.state.tasks)
        )
        await app.state.http.aclose()
        await app.state.anthropic.close()
        await app.state.jobs.close()


app = FastAPI(title="agent-playground", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs_router)
app.include_router(health_router)
