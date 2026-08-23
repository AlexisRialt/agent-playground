"""Postgres-backed job store — the durable one the server runs on.

Uses generic SQLAlchemy Core statements (update-then-insert, not a
dialect-specific `ON CONFLICT`) so the exact same code path is exercised by
tests against an in-memory SQLite engine as runs against real Postgres in
production. `log` and `tool_calls` are JSON, so a job round-trips through
exactly the same shape the API serves. Timestamps are stored as
`timestamptz` and converted back to the ISO strings the `Job` dataclass
carries.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import jobs as jobs_table
from app.jobs.job import Job
from app.jobs.store import JobStore


def _to_row(job: Job) -> dict[str, Any]:
    payload = job.to_dict()
    return {
        **payload,
        "created_at": datetime.fromisoformat(payload["created_at"]),
        "updated_at": datetime.fromisoformat(payload["updated_at"]),
    }


def _as_utc(dt: datetime) -> datetime:
    """SQLite's `DateTime` drops tzinfo on round-trip; every timestamp this
    store writes is already UTC (`now_iso()`), so a naive read back is UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _from_row(row: Mapping[str, Any]) -> Job:
    payload = dict(row)
    payload["created_at"] = _as_utc(payload["created_at"]).isoformat()
    payload["updated_at"] = _as_utc(payload["updated_at"]).isoformat()
    return Job.from_dict(payload)


class PostgresJobStore(JobStore):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, task: str) -> Job:
        job = Job(task=task)
        await self.save(job)
        return job

    async def get(self, job_id: str) -> Job | None:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(jobs_table).where(jobs_table.c.id == job_id)
            )
            row = result.mappings().first()
        return _from_row(row) if row is not None else None

    async def list(self) -> list[Job]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(jobs_table).order_by(jobs_table.c.created_at, jobs_table.c.id)
            )
            rows = result.mappings().all()
        return [_from_row(row) for row in rows]

    async def save(self, job: Job) -> None:
        values = _to_row(job)
        update_values = {
            k: v for k, v in values.items() if k not in ("id", "created_at")
        }
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(jobs_table)
                .where(jobs_table.c.id == values["id"])
                .values(**update_values)
            )
            if result.rowcount == 0:
                await conn.execute(insert(jobs_table).values(**values))

    async def close(self) -> None:
        await self._engine.dispose()
