"""Postgres connection pool and schema.

The app keeps one `asyncpg` pool for the process lifetime (built in the lifespan
handler) and hands it to `PostgresJobStore`. The schema is small enough that we
create it on startup rather than pulling in a migration tool — if the table shape
ever changes, that's the point to reach for Alembic.
"""

from __future__ import annotations

import json

import asyncpg
from loguru import logger as log

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT        NOT NULL,
    task        TEXT        NOT NULL,
    log         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    tool_calls  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    result      TEXT,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at);
"""


async def _register_json_codecs(conn: asyncpg.Connection) -> None:
    """Hand `log`/`tool_calls` back as Python lists instead of JSON strings."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def create_pool(
    dsn: str, *, min_size: int = 1, max_size: int = 10
) -> asyncpg.Pool:
    """Connect to Postgres and make sure the schema exists."""
    pool = await asyncpg.create_pool(
        dsn, min_size=min_size, max_size=max_size, init=_register_json_codecs
    )
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    log.info("postgres: pool ready (min={} max={}), schema applied", min_size, max_size)
    return pool
