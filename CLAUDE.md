# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`agent-playground` is a scratch project for experimenting with LLM agents. It targets **Python >= 3.14** and is managed with [uv](https://docs.astral.sh/uv/).

It currently hosts a **FastAPI server that runs Claude-powered agent jobs**: you `POST /jobs` a text task, the server runs a Claude agent in the background, and you poll `GET /jobs/{id}` for the plan, tool calls, and result. The agent has exactly two tools — a sandboxed filesystem and Google search.

## Architecture

The app lives under `app/` (root `main.py` is just the uvicorn launcher):

- `app/main.py` — FastAPI app + routes (`POST /jobs`, `GET /jobs/{id}`, `GET /jobs`, `GET /healthz`). Jobs run as detached `asyncio` tasks; shared `AsyncAnthropic` + `httpx` clients are created in the lifespan handler and stored on `app.state`.
- `app/agent.py` — the agent itself: a **manual** Claude tool-use loop (not the SDK tool runner, so each plan step and tool call is recorded into the `Job`). Uses `claude-opus-4-8` with adaptive thinking. The system prompt tells the agent to write a plan first, then act.
- `app/tools/filesystem.py` — one tool (`list`/`read`/`write`) confined to a per-job `workspace/<job_id>/` sandbox; every path is resolved and checked to stay inside the root.
- `app/tools/search.py` — the `google_search` tool via SerpAPI (`GET serpapi.com/search`, `api_key` query param, results under `organic_results`); returns a clear stub message when `SERPER_API_KEY` is unset, so the server runs with zero extra setup.
- `app/jobs.py` — in-memory `JobStore` (lost on restart; swap for Redis/DB for durability).
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
- Run a single test: `uv run pytest path/to/test.py::test_name`

No test files exist yet; `pytest` is installed and ready for when they're added.

## Environment / Secrets

`.envrc` (direnv) loads `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the macOS Keychain via `security find-generic-password`. Both agent SDKs are expected to be available. Run `direnv allow` once to activate, or set these vars manually on other platforms.
