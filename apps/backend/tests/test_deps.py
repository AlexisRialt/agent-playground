"""`app.deps` — the FastAPI dependency providers wired onto `request.app.state`.

Each provider is a plain function of `request.app.state`, so it's tested
against a bare stand-in rather than a real `Request` (which only these
providers ever read from).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.deps import (
    get_anthropic_client,
    get_http_client,
    get_job_store,
    get_task_registry,
)


def _request(**state) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)))


def test_get_anthropic_client_reads_app_state():
    sentinel = object()
    assert get_anthropic_client(_request(anthropic=sentinel)) is sentinel


def test_get_http_client_reads_app_state():
    sentinel = object()
    assert get_http_client(_request(http=sentinel)) is sentinel


def test_get_job_store_reads_app_state():
    sentinel = object()
    assert get_job_store(_request(jobs=sentinel)) is sentinel


def test_get_task_registry_reads_app_state():
    tasks = {object()}
    assert get_task_registry(_request(tasks=tasks)) is tasks
