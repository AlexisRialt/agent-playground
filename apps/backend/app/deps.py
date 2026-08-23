"""FastAPI dependency providers.

The lifespan handler in `app/main.py` is still what builds the shared clients
and job store and hangs them on `app.state` — that part doesn't change.  What
changes is how endpoints get at them: instead of pulling `request.app.state`
apart by hand, they declare what they need via `Depends()` (or the `Annotated`
aliases below), and FastAPI resolves it per-request. That's what makes the
dependency swappable in tests via `app.dependency_overrides`, without
monkeypatching `app.state` or the handler module.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import httpx
from anthropic import AsyncAnthropic
from fastapi import Depends, Request

from app.jobs import JobStore


def get_anthropic_client(request: Request) -> AsyncAnthropic:
    return request.app.state.anthropic


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def get_job_store(request: Request) -> JobStore:
    return request.app.state.jobs


def get_task_registry(request: Request) -> set[asyncio.Task]:
    """The set of in-flight background job tasks, kept so they aren't GC'd."""
    return request.app.state.tasks


AnthropicClient = Annotated[AsyncAnthropic, Depends(get_anthropic_client)]
HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]
JobStoreDep = Annotated[JobStore, Depends(get_job_store)]
TaskRegistry = Annotated[set[asyncio.Task], Depends(get_task_registry)]
