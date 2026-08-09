"""FastAPI server.

POST /jobs      -> submit a task; returns a job id and starts the agent in the background.
GET  /jobs/{id} -> poll a job's status, plan/log, tool calls, and final result.
GET  /jobs      -> list all jobs (summaries).
GET  /healthz   -> liveness check.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

import httpx
from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException
from loguru import logger as log
from pydantic import BaseModel, Field

from app.agent import run_agent
from app.config import settings
from app.jobs import Job, JobStatus, JobStore
from app.logs import job_logger, setup_logging, short
from app.tools.filesystem import Filesystem

setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Shared clients live for the process lifetime.
    app.state.anthropic = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env
    app.state.http = httpx.AsyncClient()
    app.state.jobs = JobStore()
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


app = FastAPI(title="agent-playground", version="0.1.0", lifespan=lifespan)


class CreateJobRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, description="The task for the agent to work on."
    )


class CreateJobResponse(BaseModel):
    id: str
    status: str


async def _execute_job(app: FastAPI, job: Job) -> None:
    jlog = job_logger(job.id)
    job.status = JobStatus.RUNNING
    job.touch()
    fs = Filesystem(settings.workspace_root / job.id)
    jlog.info("job running (workspace={})", fs.root)
    started = time.perf_counter()
    try:
        result = await run_agent(job, fs, app.state.anthropic, app.state.http)
        job.result = result
        job.status = JobStatus.COMPLETED
        jlog.info(
            "job completed in {:.1f}s after {} tool call(s): {}",
            time.perf_counter() - started,
            len(job.tool_calls),
            short(result, 600),
        )
    except Exception as exc:  # noqa: BLE001 - job boundary: record any failure as job state
        job.error = f"{type(exc).__name__}: {exc}"
        job.status = JobStatus.FAILED
        jlog.exception("job FAILED after {:.1f}s", time.perf_counter() - started)
    finally:
        job.touch()


@app.post("/jobs", response_model=CreateJobResponse, status_code=202)
async def create_job(req: CreateJobRequest) -> CreateJobResponse:
    job = app.state.jobs.create(req.text)
    job_logger(job.id).info("job created: {}", short(req.text, 300))
    task = asyncio.create_task(_execute_job(app, job))
    # Track the task so it isn't garbage-collected mid-run; drop it when done.
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)
    return CreateJobResponse(id=job.id, status=job.status.value)


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = app.state.jobs.get(job_id)
    if job is None:
        log.warning("poll for unknown job {}", job_id)
        raise HTTPException(status_code=404, detail="job not found")
    log.debug("poll job {} -> {}", job_id[:8], job.status.value)
    return job.to_dict()


@app.get("/jobs")
async def list_jobs() -> list[dict]:
    return [
        {
            "id": j.id,
            "status": j.status.value,
            "task": j.task,
            "created_at": j.created_at,
            "updated_at": j.updated_at,
        }
        for j in app.state.jobs.list()
    ]


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
