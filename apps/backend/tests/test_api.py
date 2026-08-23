"""HTTP endpoints, exercised through the real FastAPI app.

The app's lifespan is what builds `app.state`, so every test drives the app via
`TestClient` as a context manager. `execute_job` is stubbed out — this file is
about the HTTP contract, not about running agents.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.api import jobs as jobs_api
from app.deps import get_job_store
from app.jobs import InMemoryJobStore, JobStatus
from tests.conftest import run_sync


@pytest.fixture
def executed():
    """Records the jobs handed to the (stubbed) background runner."""
    return []


@pytest.fixture
def in_memory_store(monkeypatch):
    """Keep the app off Postgres: the lifespan opens an in-memory store."""

    async def open_in_memory_store():
        return InMemoryJobStore()

    monkeypatch.setattr(app_main, "open_job_store", open_in_memory_store)


@pytest.fixture
def client(monkeypatch, tmp_path, patch_settings, executed, in_memory_store):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    patch_settings("app.main", workspace_root=tmp_path / "workspace")

    async def stub_execute_job(job, anthropic_client, http_client, store):
        executed.append(job)
        job.status = JobStatus.COMPLETED
        job.result = f"handled: {job.task}"
        await store.save(job)

    monkeypatch.setattr(jobs_api, "execute_job", stub_execute_job)

    with TestClient(app_main.app) as test_client:
        yield test_client


def stored(job_id):
    """Read a job straight out of the running app's store."""
    return run_sync(app_main.app.state.jobs.get(job_id))


def wait_for(predicate, timeout: float = 5.0) -> None:
    """Give the app's event loop a chance to finish background tasks."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the background task")


# --------------------------------------------------------------------------
# GET /healthz
# --------------------------------------------------------------------------


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --------------------------------------------------------------------------
# POST /jobs
# --------------------------------------------------------------------------


def test_create_job_returns_202_with_an_id_and_pending_status(client):
    response = client.post("/jobs", json={"text": "summarise the news"})

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"id", "status"}
    assert body["status"] == "pending"
    assert body["id"]


def test_create_job_stores_the_job(client):
    job_id = client.post("/jobs", json={"text": "a task"}).json()["id"]
    job = stored(job_id)
    assert job is not None
    assert job.task == "a task"


def test_create_job_schedules_the_background_runner(client, executed):
    job_id = client.post("/jobs", json={"text": "background me"}).json()["id"]
    wait_for(lambda: executed)
    assert [j.id for j in executed] == [job_id]


def test_the_background_task_is_tracked_then_discarded(client, executed):
    client.post("/jobs", json={"text": "t"})
    wait_for(lambda: executed)
    wait_for(lambda: not app_main.app.state.tasks)


def test_the_background_result_is_visible_on_the_next_poll(client, executed):
    job_id = client.post("/jobs", json={"text": "t"}).json()["id"]
    wait_for(lambda: executed)

    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "completed"
    assert body["result"] == "handled: t"


def test_each_submission_gets_a_distinct_id(client):
    first = client.post("/jobs", json={"text": "one"}).json()["id"]
    second = client.post("/jobs", json={"text": "one"}).json()["id"]
    assert first != second


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing field
        {"text": ""},  # min_length=1
        {"text": None},
        {"task": "wrong field name"},
        {"text": 123},
    ],
)
def test_invalid_create_payloads_are_rejected(client, payload, executed):
    assert client.post("/jobs", json=payload).status_code == 422
    assert executed == []


def test_long_and_unicode_tasks_are_accepted(client):
    task = "分析 this — " + "x" * 5000
    job_id = client.post("/jobs", json={"text": task}).json()["id"]
    assert client.get(f"/jobs/{job_id}").json()["task"] == task


def test_extra_fields_are_ignored(client):
    response = client.post("/jobs", json={"text": "t", "priority": "urgent"})
    assert response.status_code == 202


# --------------------------------------------------------------------------
# GET /jobs/{id}
# --------------------------------------------------------------------------


def test_get_job_returns_the_full_record(client):
    job_id = client.post("/jobs", json={"text": "inspect me"}).json()["id"]
    body = client.get(f"/jobs/{job_id}").json()

    assert set(body) == {
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
    assert body["id"] == job_id
    assert body["task"] == "inspect me"


def test_get_job_exposes_recorded_tool_calls(client):
    job_id = client.post("/jobs", json={"text": "t"}).json()["id"]
    job = stored(job_id)
    job.add_log("PLAN: search then write")
    job.add_tool_call("google_search", {"query": "q"}, "1. result", False)
    run_sync(app_main.app.state.jobs.save(job))

    body = client.get(f"/jobs/{job_id}").json()

    assert body["log"] == ["PLAN: search then write"]
    assert body["tool_calls"] == [
        {
            "tool": "google_search",
            "input": {"query": "q"},
            "output": "1. result",
            "is_error": False,
            "at": job.tool_calls[0].at,
        }
    ]


def test_get_unknown_job_is_404(client):
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "job not found"}


def test_a_failed_job_reports_its_error(client):
    job_id = client.post("/jobs", json={"text": "t"}).json()["id"]
    # Let the stubbed runner finish first, so it can't overwrite the state below.
    wait_for(lambda: not app_main.app.state.tasks)
    job = stored(job_id)
    job.status = JobStatus.FAILED
    job.error = "RuntimeError: boom"
    job.result = None
    run_sync(app_main.app.state.jobs.save(job))

    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "failed"
    assert body["error"] == "RuntimeError: boom"
    assert body["result"] is None


# --------------------------------------------------------------------------
# GET /jobs
# --------------------------------------------------------------------------


def test_list_jobs_is_empty_initially(client):
    assert client.get("/jobs").json() == []


def test_list_jobs_returns_summaries_in_submission_order(client, executed):
    ids = [
        client.post("/jobs", json={"text": f"task {i}"}).json()["id"] for i in range(3)
    ]
    wait_for(lambda: len(executed) == 3)

    listing = client.get("/jobs").json()

    assert [row["id"] for row in listing] == ids
    assert [row["task"] for row in listing] == ["task 0", "task 1", "task 2"]


def test_list_jobs_omits_the_heavy_fields(client):
    client.post("/jobs", json={"text": "t"})
    (row,) = client.get("/jobs").json()
    assert set(row) == {"id", "status", "task", "created_at", "updated_at"}


def test_the_store_is_per_app_instance(client):
    """State lives on `app.state`, rebuilt by the lifespan on each startup."""
    client.post("/jobs", json={"text": "t"})
    assert len(client.get("/jobs").json()) == 1


# --------------------------------------------------------------------------
# Dependency injection
# --------------------------------------------------------------------------


def test_the_job_store_dependency_is_overridable(client):
    """Endpoints resolve the store via `Depends(get_job_store)`, not `app.state`
    directly, so a test can swap it out per-request with `dependency_overrides`
    rather than reaching into the app's internals."""
    override_store = InMemoryJobStore()
    job = run_sync(override_store.create("from the override"))

    app_main.app.dependency_overrides[get_job_store] = lambda: override_store
    try:
        body = client.get(f"/jobs/{job.id}").json()
    finally:
        app_main.app.dependency_overrides.clear()

    assert body["task"] == "from the override"


# --------------------------------------------------------------------------
# Background task bookkeeping
# --------------------------------------------------------------------------


def test_an_in_flight_task_is_held_by_a_strong_reference(
    monkeypatch, tmp_path, patch_settings, in_memory_store
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    patch_settings("app.main", workspace_root=tmp_path / "workspace")
    started, release = threading.Event(), threading.Event()

    async def blocking_execute_job(job, anthropic_client, http_client, store):
        import asyncio

        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        job.status = JobStatus.COMPLETED
        await store.save(job)

    monkeypatch.setattr(jobs_api, "execute_job", blocking_execute_job)

    with TestClient(app_main.app) as test_client:
        job_id = test_client.post("/jobs", json={"text": "slow"}).json()["id"]
        assert started.wait(5)
        assert len(app_main.app.state.tasks) == 1
        assert test_client.get(f"/jobs/{job_id}").json()["status"] == "pending"

        release.set()
        wait_for(lambda: not app_main.app.state.tasks)
        assert test_client.get(f"/jobs/{job_id}").json()["status"] == "completed"


def test_a_crashing_background_task_does_not_break_the_server(
    monkeypatch, tmp_path, patch_settings, in_memory_store
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    patch_settings("app.main", workspace_root=tmp_path / "workspace")

    async def exploding_execute_job(job, anthropic_client, http_client, store):
        raise RuntimeError("runner blew up")

    monkeypatch.setattr(jobs_api, "execute_job", exploding_execute_job)

    with TestClient(app_main.app) as test_client:
        job_id = test_client.post("/jobs", json={"text": "t"}).json()["id"]
        wait_for(lambda: not app_main.app.state.tasks)
        assert test_client.get(f"/jobs/{job_id}").status_code == 200
        assert test_client.get("/healthz").status_code == 200
