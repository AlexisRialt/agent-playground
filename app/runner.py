"""Runs a job to completion in the background.

The HTTP layer hands a freshly created `Job` here and returns immediately; this
module owns the job's lifecycle — sandbox setup, running the agent, and recording
the outcome (success or failure) back onto the job record.
"""

from __future__ import annotations

import time

import httpx
from anthropic import AsyncAnthropic

from app.agent import run_agent
from app.config import settings
from app.jobs import Job, JobStatus
from app.logs import job_logger, short
from app.tools.filesystem import Filesystem


async def execute_job(
    job: Job, anthropic_client: AsyncAnthropic, http_client: httpx.AsyncClient
) -> None:
    jlog = job_logger(job.id)
    job.status = JobStatus.RUNNING
    job.touch()
    fs = Filesystem(settings.workspace_root / job.id)
    jlog.info("job running (workspace={})", fs.root)
    started = time.perf_counter()
    try:
        result = await run_agent(job, fs, anthropic_client, http_client)
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
