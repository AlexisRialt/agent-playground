"""The job store interface.

Two implementations live alongside this module: `PostgresJobStore` (what the
server runs on) and `InMemoryJobStore` (a dependency-free stand-in used by the
tests). Everything is async because the real backing store does I/O.

Writes are explicit: the runner mutates a `Job` in memory and calls `save()` at
each checkpoint, so a poll of `GET /jobs/{id}` sees progress as it happens.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.jobs.job import Job


class JobStore(ABC):
    @abstractmethod
    async def create(self, task: str) -> Job:
        """Persist a fresh pending job for `task` and return it."""

    @abstractmethod
    async def get(self, job_id: str) -> Job | None:
        """Load one job, or None if there is no such id."""

    @abstractmethod
    async def list(self) -> list[Job]:
        """Every job, oldest first."""

    @abstractmethod
    async def save(self, job: Job) -> None:
        """Write the current state of `job` back to storage."""

    async def close(self) -> None:
        """Release any resources held by the store. No-op by default."""
