"""The `jobs` table definition and the async engine the job store runs on.

Schema is owned by Alembic (`alembic upgrade head`, run as a separate step
before the app starts — see `alembic/`); this module only describes the
table for query-building and connects to it. It does not create or alter
anything.
"""

from __future__ import annotations

from loguru import logger as log
from sqlalchemy import Column, DateTime, Index, MetaData, Table, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.types import JSON

metadata = MetaData()

# `log`/`tool_calls` are `jsonb` on Postgres (native, indexable) but fall back
# to SQLAlchemy's generic JSON on any other dialect — this is what lets tests
# build this same Table against an in-memory SQLite engine.
_json_type = JSON().with_variant(JSONB(), "postgresql")

jobs = Table(
    "jobs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("task", Text, nullable=False),
    Column("log", _json_type, nullable=False, server_default=text("'[]'")),
    Column("tool_calls", _json_type, nullable=False, server_default=text("'[]'")),
    Column("result", Text),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Index("jobs_created_at_idx", "created_at"),
)


async def build_engine(
    dsn: str, *, pool_size: int = 5, max_overflow: int = 5
) -> AsyncEngine:
    """Build the async engine and confirm the database is reachable."""
    engine = create_async_engine(dsn, pool_size=pool_size, max_overflow=max_overflow)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    log.info(
        "postgres: engine ready (pool_size={} max_overflow={})", pool_size, max_overflow
    )
    return engine
