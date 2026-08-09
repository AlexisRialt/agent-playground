"""App wiring: the lifespan handler, mounted routers, and the launcher."""

from __future__ import annotations

import httpx
import pytest
from anthropic import AsyncAnthropic
from fastapi.testclient import TestClient

import main as launcher
from app import main as app_main
from app.jobs import JobStore


@pytest.fixture
def started_app(monkeypatch, tmp_path, patch_settings):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    settings = patch_settings("app.main", workspace_root=tmp_path / "workspace")
    with TestClient(app_main.app):
        yield app_main.app, settings


# --------------------------------------------------------------------------
# App metadata and routes
# --------------------------------------------------------------------------


def test_app_metadata():
    assert app_main.app.title == "agent-playground"
    assert app_main.app.version == "0.1.0"


def test_both_routers_are_mounted():
    paths = app_main.app.openapi()["paths"]
    assert set(paths) >= {"/jobs", "/jobs/{job_id}", "/healthz"}
    assert set(paths["/jobs"]) == {"get", "post"}


def test_openapi_documents_the_job_endpoints():
    paths = app_main.app.openapi()["paths"]
    assert paths["/jobs"]["post"]["responses"].get("202")
    assert paths["/jobs"]["post"]["tags"] == ["jobs"]
    assert paths["/healthz"]["get"]["tags"] == ["health"]


# --------------------------------------------------------------------------
# Lifespan
# --------------------------------------------------------------------------


def test_lifespan_populates_shared_state(started_app):
    app, _ = started_app
    assert isinstance(app.state.anthropic, AsyncAnthropic)
    assert isinstance(app.state.http, httpx.AsyncClient)
    assert isinstance(app.state.jobs, JobStore)
    assert app.state.tasks == set()


def test_lifespan_creates_the_workspace_root(started_app):
    _, settings = started_app
    assert settings.workspace_root.is_dir()


def test_lifespan_tolerates_an_existing_workspace_root(
    monkeypatch, tmp_path, patch_settings
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "leftover").mkdir()
    patch_settings("app.main", workspace_root=root)

    with TestClient(app_main.app):
        pass

    assert (root / "leftover").is_dir()


def test_shutdown_closes_the_http_client(monkeypatch, tmp_path, patch_settings):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    patch_settings("app.main", workspace_root=tmp_path / "workspace")

    with TestClient(app_main.app):
        client = app_main.app.state.http
        assert not client.is_closed

    assert client.is_closed


def test_each_startup_gets_a_fresh_job_store(monkeypatch, tmp_path, patch_settings):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    patch_settings("app.main", workspace_root=tmp_path / "workspace")

    with TestClient(app_main.app) as client:
        client.post("/jobs", json={"text": "t"})
        first_store = app_main.app.state.jobs
        assert len(first_store.list()) == 1

    with TestClient(app_main.app) as client:
        assert app_main.app.state.jobs is not first_store
        assert client.get("/jobs").json() == []


# --------------------------------------------------------------------------
# Launcher (root main.py)
# --------------------------------------------------------------------------


def test_launcher_configures_logging_then_starts_uvicorn(monkeypatch):
    order: list[str] = []
    captured: dict = {}

    monkeypatch.setattr(launcher, "setup_logging", lambda level: order.append(level))

    def fake_run(target, **kwargs):
        order.append("uvicorn")
        captured.update(kwargs, target=target)

    monkeypatch.setattr(launcher.uvicorn, "run", fake_run)

    launcher.main()

    assert order == [launcher.settings.log_level, "uvicorn"]
    assert captured["target"] == "app.main:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["reload"] is False
    assert captured["log_level"] == launcher.settings.log_level.lower()
    # uvicorn must not install its own handlers; logs go through loguru.
    assert captured["log_config"] is None
