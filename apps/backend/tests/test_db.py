"""`app.db` — the `jobs` Table definition and the async engine builder.

Schema itself is owned by Alembic (see `tests/test_migrations.py`); what's
worth testing here is that the Table this module hands to the store and to
Alembic's `env.py` has the right shape, and that `build_engine` wires up the
engine and probes connectivity the way the app expects.
"""

from __future__ import annotations

from typing import Any, Self

import pytest

from app import db

# --------------------------------------------------------------------------
# jobs Table
# --------------------------------------------------------------------------


def test_jobs_table_declares_every_job_column():
    names = {c.name for c in db.jobs.columns}
    assert names == {
        "id",
        "status",
        "task",
        "log",
        "tool_calls",
        "result",
        "error",
        "created_at",
        "updated_at",
    }


def test_id_is_the_primary_key():
    assert [c.name for c in db.jobs.primary_key.columns] == ["id"]


def test_created_at_has_an_index():
    assert any(ix.name == "jobs_created_at_idx" for ix in db.jobs.indexes)


def test_log_and_tool_calls_use_jsonb_on_postgres():
    from sqlalchemy.dialects import postgresql

    for column in ("log", "tool_calls"):
        dialect_type = db.jobs.c[column].type.dialect_impl(postgresql.dialect())
        assert isinstance(dialect_type, postgresql.JSONB)


# --------------------------------------------------------------------------
# build_engine
# --------------------------------------------------------------------------


class _FakeResult:
    def scalar(self) -> int:
        return 1


class RecordingConnection:
    def __init__(self) -> None:
        self.executed: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class RecordingEngine:
    def __init__(self) -> None:
        self.conn = RecordingConnection()

    def connect(self) -> RecordingConnection:
        return self.conn


@pytest.fixture
def fake_create_async_engine(monkeypatch):
    """Replace `create_async_engine`; returns (dsn, kwargs, engine) it was called with."""
    calls: list[tuple[str, dict[str, Any]]] = []
    engine = RecordingEngine()

    def _create_async_engine(dsn: str, **kwargs: Any) -> RecordingEngine:
        calls.append((dsn, kwargs))
        return engine

    monkeypatch.setattr(db, "create_async_engine", _create_async_engine)
    return calls, engine


async def test_build_engine_passes_the_dsn_and_sizing_through(fake_create_async_engine):
    calls, _ = fake_create_async_engine

    await db.build_engine(
        "postgresql+asyncpg://u:p@host:5432/agent", pool_size=2, max_overflow=7
    )

    (dsn, kwargs) = calls[0]
    assert dsn == "postgresql+asyncpg://u:p@host:5432/agent"
    assert kwargs["pool_size"] == 2
    assert kwargs["max_overflow"] == 7


async def test_build_engine_probes_connectivity(fake_create_async_engine):
    _, engine = fake_create_async_engine

    await db.build_engine("postgresql+asyncpg://localhost/agent")

    assert len(engine.conn.executed) == 1


async def test_build_engine_returns_the_engine(fake_create_async_engine):
    _, engine = fake_create_async_engine

    result = await db.build_engine("postgresql+asyncpg://localhost/agent")

    assert result is engine
