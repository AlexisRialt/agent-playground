"""In-memory job store: a dict, lost on restart.

Not what the server runs on any more — `PostgresJobStore` is — but it keeps the
test suite free of a database, and it's the smallest possible reference for what
a `JobStore` has to do.
"""

from __future__ import annotations

from app.jobs.job import Job
from app.jobs.store import JobStore


class InMemoryJobStore(JobStore):
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    async def create(self, task: str) -> Job:
        job = Job(task=task)
        self._jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def list(self) -> list[Job]:
        return list(self._jobs.values())

    async def save(self, job: Job) -> None:
        # The stored object *is* the caller's, so its mutations are already
        # visible; re-registering keeps `save()` meaningful for unknown jobs.
        self._jobs[job.id] = job
