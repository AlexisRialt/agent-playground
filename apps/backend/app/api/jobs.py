"""Job endpoints.

POST /jobs      -> submit a task; returns a job id and starts the agent in the background.
GET  /jobs/{id} -> poll a job's status, plan/log, tool calls, and final result.
GET  /jobs      -> list all jobs (summaries).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from loguru import logger as log
from pydantic import BaseModel, Field

from app.logs import job_logger, short
from app.runner import execute_job

router = APIRouter(tags=["jobs"])


class CreateJobRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, description="The task for the agent to work on."
    )


class CreateJobResponse(BaseModel):
    id: str
    status: str


@router.post("/jobs", response_model=CreateJobResponse, status_code=202)
async def create_job(req: CreateJobRequest, request: Request) -> CreateJobResponse:
    state = request.app.state
    job = await state.jobs.create(req.text)
    job_logger(job.id).info("job created: {}", short(req.text, 300))
    task = asyncio.create_task(
        execute_job(job, state.anthropic, state.http, state.jobs)
    )
    # Track the task so it isn't garbage-collected mid-run; drop it when done.
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)
    return CreateJobResponse(id=job.id, status=job.status.value)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict:
    job = await request.app.state.jobs.get(job_id)
    if job is None:
        log.warning("poll for unknown job {}", job_id)
        raise HTTPException(status_code=404, detail="job not found")
    log.debug("poll job {} -> {}", job_id[:8], job.status.value)
    return job.to_dict()


@router.get("/jobs")
async def list_jobs(request: Request) -> list[dict]:
    jobs = await request.app.state.jobs.list()
    return [
        {
            "id": j.id,
            "status": j.status.value,
            "task": j.task,
            "created_at": j.created_at,
            "updated_at": j.updated_at,
        }
        for j in jobs
    ]
