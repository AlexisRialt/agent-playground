# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`agent-playground` is a scratch project for experimenting with LLM agents. It targets **Python >= 3.14** and is managed with [uv](https://docs.astral.sh/uv/).

It currently hosts a **FastAPI server that runs Claude-powered agent jobs**: you `POST /jobs` a text task, the server runs a Claude agent in the background, and you poll `GET /jobs/{id}` for the plan, tool calls, and result. The agent has exactly two tools — a sandboxed filesystem and Google search.

## Architecture

The app lives under `app/` (root `main.py` is just the uvicorn launcher):

- `app/main.py` — app wiring only: the lifespan handler (shared `AsyncAnthropic` + `httpx` clients and the `JobStore` on `app.state`) and `include_router` calls. No endpoints, no job logic.
- `app/api/` — the HTTP endpoints, one `APIRouter` per resource: `jobs.py` (`POST /jobs`, `GET /jobs/{id}`, `GET /jobs`, plus the request/response models) and `health.py` (`GET /healthz`). Handlers reach shared state via `request.app.state`.
- `app/runner.py` — `execute_job()`: owns a job's lifecycle (sandbox setup → `run_agent` → record result/error). `POST /jobs` fires it as a detached `asyncio` task, tracked in `app.state.tasks` so it isn't GC'd.
- `app/agent.py` — the agent itself: a **manual** Claude tool-use loop (not the SDK tool runner, so each plan step and tool call is recorded into the `Job`). Uses `claude-opus-4-8` with adaptive thinking. The system prompt tells the agent to write a plan first, then act.
- `app/tools/filesystem.py` — one tool (`list`/`read`/`write`) confined to a per-job `workspace/<job_id>/` sandbox; every path is resolved and checked to stay inside the root.
- `app/tools/search.py` — the `google_search` tool via SerpAPI (`GET serpapi.com/search`, `api_key` query param, results under `organic_results`); returns a clear stub message when `SERPER_API_KEY` is unset, so the server runs with zero extra setup.
- `app/jobs/` — job records, one class per module: `job.py` (`Job`), `status.py` (`JobStatus`), `tool_call.py` (`ToolCall`), `store.py` (in-memory `JobStore`, lost on restart; swap for Redis/DB for durability), `timestamps.py` (shared `now_iso()`). `app/jobs/__init__.py` re-exports all four classes, so `from app.jobs import Job, JobStatus, JobStore` still works.
- `app/config.py` — env-driven `Settings` (`AGENT_MODEL`, `AGENT_EFFORT`, `AGENT_MAX_ITERATIONS`, `AGENT_MAX_TOKENS`, `AGENT_WORKSPACE`, `SERPER_API_KEY`).

When adding LLM/agent code here, the provider is **Anthropic (Claude)** — see the `claude-api` skill before editing agent code.

## Commands

- Run the server: `uv run main.py` (serves on http://127.0.0.1:8000; interactive docs at `/docs`)
- Submit a job: `curl -X POST localhost:8000/jobs -H 'content-type: application/json' -d '{"text":"..."}'`
- Add a dependency: `uv add <package>` (`uv add --dev <package>` for dev-only; updates `pyproject.toml` and `uv.lock`)
- Sync the environment: `uv sync`
- Run an arbitrary command in the project venv: `uv run <cmd>`

### Lint / format (ruff)

- Lint: `uv run ruff check .` (autofix with `uv run ruff check --fix .`)
- Format: `uv run ruff format .`

### Tests (pytest)

- Run all tests: `uv run pytest`
- Run a single test: `uv run pytest tests/test_agent.py::test_refusal_raises`
- With coverage: `uv run --with pytest-cov pytest --cov=app --cov-report=term-missing`

`tests/` mirrors `app/` one file per module (`test_agent.py`, `test_filesystem.py`,
`test_search.py`, `test_jobs.py` for the whole `app/jobs/` package, `test_runner.py`,
`test_api.py` for both routers, `test_main.py` for app wiring + the launcher). Config
lives under `[tool.pytest.ini_options]` in `pyproject.toml`: `asyncio_mode = "auto"`,
so async tests are plain `async def` with no marker.

Nothing in the suite touches the network or a real Anthropic account:

- **Claude** — `tests/conftest.py` provides `FakeAnthropic`, which replays a queue of
  real `anthropic.types.Message` objects built by `make_message()`. Use the block
  helpers (`text_block`, `thinking_block`, `tool_use_block`) to script a run.
- **HTTP** — `mock_client()` / `json_client()` wrap `httpx.MockTransport`. The
  `http_client` fixture *raises* on any request, so accidental egress fails loudly.
- **Config** — `settings` is a frozen singleton each module imports by value, so the
  `patch_settings` fixture rebinds it per importing module:
  `patch_settings("app.agent", max_iterations=2)`. An autouse fixture forces
  `serper_api_key=None` for `app.tools.search` so a developer's exported key can't
  change results.

## Environment / Secrets

`.envrc` (direnv) loads `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the macOS Keychain via `security find-generic-password`. Both agent SDKs are expected to be available. Run `direnv allow` once to activate, or set these vars manually on other platforms.
