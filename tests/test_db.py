"""`app.db` — pool construction and the JSON codec registration.

`asyncpg.create_pool` is stubbed out; these tests are about what the module asks
of the driver, not about talking to a real server.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app import db


class RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.codecs: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, sql: str) -> None:
        self.statements.append(sql)

    async def set_type_codec(self, name: str, **kwargs: Any) -> None:
        self.codecs.append((name, kwargs))


class RecordingPool:
    def __init__(self, dsn: str, **kwargs: Any) -> None:
        self.dsn = dsn
        self.kwargs = kwargs
        self.conn = RecordingConnection()

    def acquire(self):
        conn = self.conn

        class _Acquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Acquire()


@pytest.fixture
def fake_create_pool(monkeypatch):
    """Replace `asyncpg.create_pool`; returns the list of pools it built."""
    built: list[RecordingPool] = []

    async def _create_pool(dsn, **kwargs):
        pool = RecordingPool(dsn, **kwargs)
        built.append(pool)
        return pool

    monkeypatch.setattr(db.asyncpg, "create_pool", _create_pool)
    return built


# --------------------------------------------------------------------------
# SCHEMA
# --------------------------------------------------------------------------


def test_schema_is_safe_to_re_run():
    """Startup applies it on every boot, so it must be idempotent."""
    assert "CREATE TABLE IF NOT EXISTS jobs" in db.SCHEMA
    assert "CREATE INDEX IF NOT EXISTS" in db.SCHEMA


def test_schema_declares_every_job_column():
    for column in (
        "id",
        "status",
        "task",
        "log",
        "tool_calls",
        "result",
        "error",
        "created_at",
        "updated_at",
    ):
        assert column in db.SCHEMA


def test_schema_stores_the_list_columns_as_jsonb():
    assert "log         JSONB" in db.SCHEMA
    assert "tool_calls  JSONB" in db.SCHEMA


# --------------------------------------------------------------------------
# create_pool
# --------------------------------------------------------------------------


async def test_create_pool_passes_the_dsn_and_sizing_through(fake_create_pool):
    await db.create_pool("postgresql://u:p@host:5432/agent", min_size=2, max_size=7)

    (pool,) = fake_create_pool
    assert pool.dsn == "postgresql://u:p@host:5432/agent"
    assert pool.kwargs["min_size"] == 2
    assert pool.kwargs["max_size"] == 7


async def test_create_pool_applies_the_schema(fake_create_pool):
    pool = await db.create_pool("postgresql://localhost/agent")
    assert pool.conn.statements == [db.SCHEMA]


async def test_create_pool_registers_the_codec_on_every_connection(fake_create_pool):
    await db.create_pool("postgresql://localhost/agent")

    (pool,) = fake_create_pool
    init = pool.kwargs["init"]
    conn = RecordingConnection()
    await init(conn)

    (name, options) = conn.codecs[0]
    assert name == "jsonb"
    assert options["schema"] == "pg_catalog"


async def test_the_jsonb_codec_round_trips_a_tool_call_list():
    conn = RecordingConnection()
    await db._register_json_codecs(conn)
    (_, options) = conn.codecs[0]

    payload = [{"tool": "filesystem", "input": {"command": "list"}}]
    assert options["decoder"](options["encoder"](payload)) == payload
    assert json.loads(options["encoder"](payload)) == payload
