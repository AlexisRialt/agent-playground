"""Postgres-backed job store — the durable one the server runs on.

One row per job in the `jobs` table (see `app/db.py` for the schema). `log` and
`tool_calls` are JSONB, so a job round-trips through exactly the same shape the
API serves. Timestamps are stored as `timestamptz` and converted back to the ISO
strings the `Job` dataclass carries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from app.jobs.job import Job
from app.jobs.store import JobStore

COLUMNS = "id, status, task, log, tool_calls, result, error, created_at, updated_at"

UPSERT = f"""
INSERT INTO jobs ({COLUMNS})
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
ON CONFLICT (id) DO UPDATE SET
    status     = EXCLUDED.status,
    task       = EXCLUDED.task,
    log        = EXCLUDED.log,
    tool_calls = EXCLUDED.tool_calls,
    result     = EXCLUDED.result,
    error      = EXCLUDED.error,
    updated_at = EXCLUDED.updated_at
"""


def _to_row(job: Job) -> tuple[Any, ...]:
    payload = job.to_dict()
    return (
        payload["id"],
        payload["status"],
        payload["task"],
        payload["log"],
        payload["tool_calls"],
        payload["result"],
        payload["error"],
        datetime.fromisoformat(payload["created_at"]),
        datetime.fromisoformat(payload["updated_at"]),
    )


def _from_row(row: asyncpg.Record) -> Job:
    payload = dict(row)
    payload["created_at"] = payload["created_at"].isoformat()
    payload["updated_at"] = payload["updated_at"].isoformat()
    return Job.from_dict(payload)


class PostgresJobStore(JobStore):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, task: str) -> Job:
        job = Job(task=task)
        await self.save(job)
        return job

    async def get(self, job_id: str) -> Job | None:
        row = await self._pool.fetchrow(
            f"SELECT {COLUMNS} FROM jobs WHERE id = $1", job_id
        )
        return _from_row(row) if row is not None else None

    async def list(self) -> list[Job]:
        rows = await self._pool.fetch(
            f"SELECT {COLUMNS} FROM jobs ORDER BY created_at, id"
        )
        return [_from_row(row) for row in rows]

    async def save(self, job: Job) -> None:
        await self._pool.execute(UPSERT, *_to_row(job))

    async def close(self) -> None:
        await self._pool.close()
