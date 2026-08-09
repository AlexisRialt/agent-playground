"""In-memory job store.

This is a single-process playground store — jobs live in a dict and are lost on
restart. Swap in Redis/a database if you need durability or multiple workers.
"""

from __future__ import annotations

from app.jobs.job import Job


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, task: str) -> Job:
        job = Job(task=task)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(self._jobs.values())
