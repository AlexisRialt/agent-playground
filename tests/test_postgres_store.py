"""`PostgresJobStore` — row mapping and the SQL it issues.

Driven by `FakePool` rather than a live database: what's worth testing here is
the translation between a `Job` and its row (JSON columns, `timestamptz` <->
ISO strings), not that Postgres can execute an UPSERT.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.jobs import Job, JobStatus, JobStore, PostgresJobStore, ToolCall
from tests.conftest import FakePool

CREATED = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
UPDATED = datetime(2026, 1, 1, 12, 5, 30, tzinfo=UTC)


def row(**overrides):
    """A `jobs` row as asyncpg hands it back (datetimes, decoded JSONB)."""
    return {
        "id": "job-1",
        "status": "completed",
        "task": "summarise the news",
        "log": ["PLAN: search"],
        "tool_calls": [
            {
                "tool": "google_search",
                "input": {"query": "news"},
                "output": "1. a headline",
                "is_error": False,
                "at": "2026-01-01T12:01:00+00:00",
            }
        ],
        "result": "here you go",
        "error": None,
        "created_at": CREATED,
        "updated_at": UPDATED,
    } | overrides


@pytest.fixture
def pool():
    return FakePool()


@pytest.fixture
def pg(pool):
    return PostgresJobStore(pool)


# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------


def test_it_is_a_job_store(pg):
    assert isinstance(pg, JobStore)


# --------------------------------------------------------------------------
# create / save
# --------------------------------------------------------------------------


async def test_create_writes_a_pending_job_and_returns_it(pg, pool):
    job = await pg.create("write a haiku")

    assert job.task == "write a haiku"
    assert job.status is JobStatus.PENDING
    (sql, args) = pool.executed[0]
    assert sql.strip().startswith("INSERT INTO jobs")
    assert args[0] == job.id
    assert args[1] == "pending"
    assert args[2] == "write a haiku"


async def test_save_sends_every_column_in_order(pg, pool):
    job = Job(task="t", id="job-1")
    job.add_log("PLAN")
    job.add_tool_call("filesystem", {"command": "list"}, "empty", False)
    job.status = JobStatus.FAILED
    job.error = "RuntimeError: boom"

    await pg.save(job)

    (_, args) = pool.executed[-1]
    assert args[0] == "job-1"
    assert args[1] == "failed"
    assert args[3] == ["PLAN"]
    assert args[4] == [job.tool_calls[0].to_dict()]
    assert args[5] is None  # result
    assert args[6] == "RuntimeError: boom"


async def test_save_converts_timestamps_to_datetimes(pg, pool):
    """The columns are `timestamptz`; the dataclass carries ISO strings."""
    job = Job(task="t")

    await pg.save(job)

    (_, args) = pool.executed[-1]
    created, updated = args[7], args[8]
    assert isinstance(created, datetime)
    assert created.tzinfo is not None
    assert created.isoformat() == job.created_at
    assert updated.isoformat() == job.updated_at


async def test_save_upserts_so_a_job_can_be_written_repeatedly(pg, pool):
    job = Job(task="t")

    await pg.save(job)
    job.status = JobStatus.RUNNING
    await pg.save(job)

    assert len(pool.executed) == 2
    sql = pool.executed[-1][0]
    assert "ON CONFLICT (id) DO UPDATE" in sql
    # created_at is set once, at insert; a re-save must not move it.
    assert "created_at = EXCLUDED" not in sql


# --------------------------------------------------------------------------
# get
# --------------------------------------------------------------------------


async def test_get_rebuilds_the_job_from_its_row(pool):
    pool.rows = [row()]
    job = await PostgresJobStore(pool).get("job-1")

    assert job.id == "job-1"
    assert job.status is JobStatus.COMPLETED
    assert job.task == "summarise the news"
    assert job.log == ["PLAN: search"]
    assert job.result == "here you go"
    assert job.error is None


async def test_get_restores_tool_calls_as_objects(pool):
    pool.rows = [row()]
    job = await PostgresJobStore(pool).get("job-1")

    (call,) = job.tool_calls
    assert isinstance(call, ToolCall)
    assert call.tool == "google_search"
    assert call.input == {"query": "news"}
    assert call.is_error is False


async def test_get_renders_timestamps_back_as_iso_strings(pool):
    pool.rows = [row()]
    job = await PostgresJobStore(pool).get("job-1")

    assert job.created_at == "2026-01-01T12:00:00+00:00"
    assert job.updated_at == "2026-01-01T12:05:30+00:00"


async def test_get_unknown_id_returns_none(pg):
    assert await pg.get("nope") is None


async def test_a_saved_job_round_trips_through_a_row(pg, pool):
    """save() -> row -> get() must reproduce the same API payload."""
    original = Job(task="round trip")
    original.add_log("PLAN")
    original.add_tool_call("filesystem", {"command": "read"}, "out", True)
    original.status = JobStatus.COMPLETED
    original.result = "done"

    await pg.save(original)
    (_, args) = pool.executed[-1]
    columns = [
        "id",
        "status",
        "task",
        "log",
        "tool_calls",
        "result",
        "error",
        "created_at",
        "updated_at",
    ]
    pool.rows = [dict(zip(columns, args, strict=True))]

    assert (await pg.get(original.id)).to_dict() == original.to_dict()


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


async def test_list_returns_every_row_oldest_first(pool):
    pool.rows = [row(id="a"), row(id="b")]

    jobs = await PostgresJobStore(pool).list()

    assert [j.id for j in jobs] == ["a", "b"]
    sql = pool.executed[-1][0]
    assert "ORDER BY created_at" in sql


async def test_list_is_empty_when_the_table_is(pg):
    assert await pg.list() == []


# --------------------------------------------------------------------------
# close
# --------------------------------------------------------------------------


async def test_close_closes_the_pool(pg, pool):
    await pg.close()
    assert pool.closed
