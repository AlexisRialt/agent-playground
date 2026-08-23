"""`PostgresJobStore` — behavior against a real (in-memory SQLite) engine.

Driven by the `pg_engine` fixture rather than a live Postgres: the store only
issues generic SQLAlchemy Core statements (no native `ON CONFLICT`), so the
exact same code runs unmodified against SQLite. What's worth testing here is
the translation between a `Job` and its row (JSON columns, `timestamptz` <->
ISO strings) and the store's upsert/ordering semantics — not that Postgres
itself can execute a query.
"""

from __future__ import annotations

import pytest

from app.jobs import Job, JobStatus, JobStore, PostgresJobStore, ToolCall

# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------


@pytest.fixture
def pg(pg_engine):
    return PostgresJobStore(pg_engine)


def test_it_is_a_job_store(pg):
    assert isinstance(pg, JobStore)


# --------------------------------------------------------------------------
# create / save
# --------------------------------------------------------------------------


async def test_create_writes_a_pending_job_and_returns_it(pg):
    job = await pg.create("write a haiku")

    assert job.task == "write a haiku"
    assert job.status is JobStatus.PENDING
    stored = await pg.get(job.id)
    assert stored.task == "write a haiku"
    assert stored.status is JobStatus.PENDING


async def test_save_persists_every_field(pg):
    job = Job(task="t", id="job-1")
    job.add_log("PLAN")
    job.add_tool_call("filesystem", {"command": "list"}, "empty", False)
    job.status = JobStatus.FAILED
    job.error = "RuntimeError: boom"

    await pg.save(job)

    stored = await pg.get("job-1")
    assert stored.status is JobStatus.FAILED
    assert stored.log == ["PLAN"]
    assert stored.tool_calls[0].to_dict() == job.tool_calls[0].to_dict()
    assert stored.result is None
    assert stored.error == "RuntimeError: boom"


async def test_save_upserts_so_a_job_can_be_written_repeatedly(pg):
    job = Job(task="t")

    await pg.save(job)
    created_at = (await pg.get(job.id)).created_at

    job.status = JobStatus.RUNNING
    await pg.save(job)

    reloaded = await pg.get(job.id)
    assert reloaded.status is JobStatus.RUNNING
    # created_at is set once, at insert; a re-save must not move it.
    assert reloaded.created_at == created_at


# --------------------------------------------------------------------------
# get
# --------------------------------------------------------------------------


async def test_get_rebuilds_the_job_from_its_row(pg):
    job = Job(id="job-1", task="summarise the news", result="here you go")
    job.status = JobStatus.COMPLETED
    job.add_log("PLAN: search")
    await pg.save(job)

    loaded = await pg.get("job-1")

    assert loaded.id == "job-1"
    assert loaded.status is JobStatus.COMPLETED
    assert loaded.task == "summarise the news"
    assert loaded.log == ["PLAN: search"]
    assert loaded.result == "here you go"
    assert loaded.error is None


async def test_get_restores_tool_calls_as_objects(pg):
    job = Job(id="job-1", task="t")
    job.add_tool_call("google_search", {"query": "news"}, "1. a headline", False)
    await pg.save(job)

    loaded = await pg.get("job-1")

    (call,) = loaded.tool_calls
    assert isinstance(call, ToolCall)
    assert call.tool == "google_search"
    assert call.input == {"query": "news"}
    assert call.is_error is False


async def test_get_renders_timestamps_back_as_iso_strings(pg):
    job = Job(id="job-1", task="t")
    await pg.save(job)

    loaded = await pg.get("job-1")

    assert loaded.created_at == job.created_at
    assert loaded.updated_at == job.updated_at


async def test_get_unknown_id_returns_none(pg):
    assert await pg.get("nope") is None


async def test_a_saved_job_round_trips_through_a_row(pg):
    """save() -> row -> get() must reproduce the same API payload."""
    original = Job(task="round trip")
    original.add_log("PLAN")
    original.add_tool_call("filesystem", {"command": "read"}, "out", True)
    original.status = JobStatus.COMPLETED
    original.result = "done"

    await pg.save(original)

    assert (await pg.get(original.id)).to_dict() == original.to_dict()


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


async def test_list_returns_every_row_oldest_first(pg):
    older = Job(id="a", task="t")
    older.created_at = "2026-01-01T00:00:00+00:00"
    newer = Job(id="b", task="t")
    newer.created_at = "2026-01-02T00:00:00+00:00"
    await pg.save(older)
    await pg.save(newer)

    jobs = await pg.list()

    assert [j.id for j in jobs] == ["a", "b"]


async def test_list_is_empty_when_the_table_is(pg):
    assert await pg.list() == []


# --------------------------------------------------------------------------
# close
# --------------------------------------------------------------------------


async def test_close_disposes_the_engine():
    class FakeEngine:
        def __init__(self) -> None:
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()

    await PostgresJobStore(engine).close()

    assert engine.disposed
