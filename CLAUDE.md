# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`agent-playground` is a scratch monorepo for experimenting with LLM agents, split into:

- **`apps/backend`** — a **FastAPI server that runs Claude-powered agent jobs**
  (Python >= 3.14, managed with [uv](https://docs.astral.sh/uv/)). You `POST /jobs`
  a text task, the server runs a Claude agent in the background, and you poll
  `GET /jobs/{id}` for the plan, tool calls, and result. The agent has exactly
  two tools — a sandboxed filesystem and Google search. Jobs are persisted in
  **PostgreSQL** via **SQLAlchemy** (async Core), with schema managed by
  **Alembic** migrations.
- **`apps/frontend`** — a **Next.js (TypeScript) job dashboard** that talks to
  the backend over HTTP: a form to submit a task, a polling list of jobs, and a
  polling detail view of a job's plan/log, tool calls, and result.

`docker-compose.yml` (repo root) runs the database, backend, and frontend
together.

## Architecture

### Backend (`apps/backend/`)

Root `apps/backend/main.py` is just the uvicorn launcher; the app lives under `apps/backend/app/`:

- `app/main.py` — app wiring only: the lifespan handler (shared `AsyncAnthropic` + `httpx` clients and the `JobStore` on `app.state`), CORS middleware (allows the frontend's origin, `CORS_ORIGINS`), and `include_router` calls. No endpoints, no job logic. `open_job_store()` is split out of the lifespan as the one seam the tests patch to stay off Postgres.
- `app/api/` — the HTTP endpoints, one `APIRouter` per resource: `jobs.py` (`POST /jobs`, `GET /jobs/{id}`, `GET /jobs`, plus the request/response models) and `health.py` (`GET /healthz`). Handlers reach shared state via `request.app.state`.
- `app/runner.py` — `execute_job()`: owns a job's lifecycle (sandbox setup → `run_agent` → record result/error) **and its writes**. It saves the job when it starts, after every agent iteration (via the `on_progress` callback it hands `run_agent`), and when it finishes — so a poll mid-run sees live progress. `POST /jobs` fires it as a detached `asyncio` task, tracked in `app.state.tasks` so it isn't GC'd.
- `app/agent.py` — the agent itself: a **manual** Claude tool-use loop (not the SDK tool runner, so each plan step and tool call is recorded into the `Job`). Uses `claude-opus-4-8` with adaptive thinking. The system prompt tells the agent to write a plan first, then act. Takes an optional `on_progress` coroutine, awaited once per non-final iteration.
- `app/tools/filesystem.py` — one tool (`list`/`read`/`write`) confined to a per-job `workspace/<job_id>/` sandbox; every path is resolved and checked to stay inside the root.
- `app/tools/search.py` — the `google_search` tool via SerpAPI (`GET serpapi.com/search`, `api_key` query param, results under `organic_results`); returns a clear stub message when `SERPER_API_KEY` is unset, so the server runs with zero extra setup.
- `app/db.py` — the SQLAlchemy Core `jobs` `Table`/`MetaData` and `build_engine()` (builds the async engine, `postgresql+asyncpg://`, and probes connectivity). It does **not** create or alter schema — that's Alembic's job exclusively (`apps/backend/alembic/`, initial revision mirrors this `Table`); `alembic upgrade head` is a separate step run before the app starts (see Commands and Docker below). `asyncpg` is still a dependency but only as SQLAlchemy's driver — nothing calls it directly anymore.
- `app/jobs/` — job records and stores, one class per module: `job.py` (`Job`, incl. `to_dict()`/`from_dict()`), `status.py` (`JobStatus`), `tool_call.py` (`ToolCall`), `timestamps.py` (shared `now_iso()`), `store.py` (the abstract async `JobStore`), `postgres_store.py` (`PostgresJobStore` — what the server runs on), `memory_store.py` (`InMemoryJobStore` — dependency-free, used by tests). `app/jobs/__init__.py` re-exports them all.
- `app/config.py` — env-driven `Settings` (`AGENT_MODEL`, `AGENT_EFFORT`, `AGENT_MAX_ITERATIONS`, `AGENT_MAX_TOKENS`, `AGENT_WORKSPACE`, `SERPER_API_KEY`, `LOG_LEVEL`, `DATABASE_URL`, `HOST`, `PORT`, `CORS_ORIGINS`).

The store API is **async** (`create`/`get`/`list`/`save`/`close`). A `Job` is mutated in memory as the agent works and flushed with `save()`; nothing writes to the database implicitly.

When adding LLM/agent code here, the provider is **Anthropic (Claude)** — see the `claude-api` skill before editing agent code.

### Frontend (`apps/frontend/`)

A Next.js App Router project (TypeScript, Tailwind, npm), talking to the
backend purely client-side over `fetch` — no server-side rendering of job
data, no backend-for-frontend layer.

- `src/lib/api.ts` — `API_BASE_URL` (from `NEXT_PUBLIC_API_URL`, default
  `http://localhost:8000`), the `Job`/`ToolCall`/`JobSummary` types (mirroring
  `apps/backend/app/jobs/job.py`'s `to_dict()` shape), and the `createJob` /
  `listJobs` / `getJob` fetch wrappers. This is the one file to update if the
  backend's job JSON shape changes.
- `src/app/page.tsx` — client component: submit-job form + a table of jobs,
  polling `GET /jobs` every ~3s.
- `src/app/jobs/[id]/page.tsx` — client component: polls `GET /jobs/{id}`
  every ~2s while the job is `pending`/`running`, renders the log, tool calls,
  and result/error. Uses `useParams()` (not the `params` prop) since it's a
  client-component page.
- `src/components/StatusBadge.tsx` — shared status → color mapping.
- `next.config.ts` — `output: "standalone"`, required for the Docker image.

`NEXT_PUBLIC_API_URL` is inlined into the client bundle at **build** time, not
read at runtime — set it before `npm run build` / in the Docker build arg, not
just in the running container's environment.

## Commands

- Run the whole stack (frontend + backend + postgres): `docker compose up --build` (needs `ANTHROPIC_API_KEY` exported; run from the repo root) — a one-off `migrate` service runs `alembic upgrade head` and must exit 0 before `app` starts
- Run just the database, then the backend on the host: `docker compose up -d db`, `cd apps/backend && uv run alembic upgrade head`, then `uv run main.py`
- Run the backend: `cd apps/backend && uv run main.py` (serves on http://127.0.0.1:8000; interactive docs at `/docs`) — needs a reachable `DATABASE_URL` with the schema already migrated (see below)
- Apply database migrations: `cd apps/backend && uv run alembic upgrade head`
- Author a migration after changing `app/db.py`'s `jobs` `Table`: `cd apps/backend && uv run alembic revision --autogenerate -m "..."`, then review the generated file before committing it
- Run the frontend: `cd apps/frontend && npm run dev` (serves on http://localhost:3000) — needs the backend reachable at `NEXT_PUBLIC_API_URL`
- Submit a job: `curl -X POST localhost:8000/jobs -H 'content-type: application/json' -d '{"text":"..."}'`
- Inspect stored jobs: `docker compose exec db psql -U agent -d agent -c 'SELECT id, status, task FROM jobs;'`
- Add a backend dependency: `cd apps/backend && uv add <package>` (`uv add --dev <package>` for dev-only; updates `pyproject.toml` and `uv.lock`)
- Add a frontend dependency: `cd apps/frontend && npm install <package>`
- Sync the backend environment: `cd apps/backend && uv sync`
- Run an arbitrary command in the backend's venv: `cd apps/backend && uv run <cmd>`

### Backend lint / format (ruff)

Run from `apps/backend/`:

- Lint: `uv run ruff check .` (autofix with `uv run ruff check --fix .`)
- Format: `uv run ruff format .`

### Backend tests (pytest)

Run from `apps/backend/`:

- Run all tests: `uv run pytest`
- Run a single test: `uv run pytest tests/test_agent.py::test_refusal_raises`
- With coverage: `uv run --with pytest-cov pytest --cov=app --cov-report=term-missing`

`tests/` mirrors `app/` one file per module (`test_agent.py`, `test_filesystem.py`,
`test_search.py`, `test_jobs.py` for the job records + `InMemoryJobStore`,
`test_postgres_store.py`, `test_db.py`, `test_migrations.py`, `test_runner.py`,
`test_api.py` for both routers, `test_main.py` for app wiring + the launcher). Config
lives under `[tool.pytest.ini_options]` in `apps/backend/pyproject.toml`:
`asyncio_mode = "auto"`, so async tests are plain `async def` with no marker.

Nothing in the suite touches the network, a real Anthropic account, or a live database:

- **Claude** — `tests/conftest.py` provides `FakeAnthropic`, which replays a queue of
  real `anthropic.types.Message` objects built by `make_message()`. Use the block
  helpers (`text_block`, `thinking_block`, `tool_use_block`) to script a run.
- **HTTP** — `mock_client()` / `json_client()` wrap `httpx.MockTransport`. The
  `http_client` fixture *raises* on any request, so accidental egress fails loudly.
- **Postgres** — the `store` fixture is an `InMemoryJobStore`. `PostgresJobStore`
  itself is tested in `test_postgres_store.py` against the `pg_engine` fixture, a
  real **in-memory SQLite** engine built from the same `app.db.jobs` `Table` — the
  store only issues generic SQLAlchemy Core statements (a portable
  update-then-insert upsert, not a Postgres-only `ON CONFLICT`), so it runs
  unmodified there. Alembic's actual DDL (`postgresql.JSONB` etc.) is Postgres-only
  and isn't executed in tests; `test_migrations.py` only checks the revision history
  is well-formed and linear. App-level tests patch `app.main.open_job_store`. Because
  `TestClient` runs the loop on another thread, sync tests reach the store through
  `run_sync()`.
- **Config** — `settings` is a frozen singleton each module imports by value, so the
  `patch_settings` fixture rebinds it per importing module:
  `patch_settings("app.agent", max_iterations=2)`. An autouse fixture forces
  `serper_api_key=None` for `app.tools.search` so a developer's exported key can't
  change results.

### Frontend lint / type-check

Run from `apps/frontend/`:

- Lint: `npm run lint`
- Type-check: `npx tsc --noEmit`
- Build (also type-checks): `npm run build`

## Docker

Two Dockerfiles, both built by the repo-root `docker-compose.yml`:

- `apps/backend/Dockerfile` — two stages: an `ghcr.io/astral-sh/uv:python3.14-trixie-slim` builder that resolves `uv.lock` into `/app/.venv` (`--no-dev`), and a `python:3.14-slim-trixie` runtime that copies only the venv + source (`main.py`, `app/`, `alembic.ini`, `alembic/`). Runs as the unprivileged `agent` user, `HOST=0.0.0.0`, workspace at `/data/workspace`. The same image serves both the `app` and `migrate` compose services below — `migrate` just overrides the container `command`.
- `apps/frontend/Dockerfile` — three stages (`deps` → `builder` → `runtime`, all `node:22-alpine`): installs from `package-lock.json`, builds with `next build` (`NEXT_PUBLIC_API_URL` passed as a build `ARG`, since it's inlined into the client bundle), and copies only `.next/standalone` + `.next/static` + `public` into the runtime stage. Runs as the unprivileged `nextjs` user.
- `docker-compose.yml` — `db` (`postgres:18-alpine`, healthchecked), `migrate` (builds `./apps/backend`, waits for `db` healthy, runs `alembic upgrade head` once and exits — `restart: "no"`), `app` (waits for `db` healthy **and** `migrate` to exit 0 via `condition: service_completed_successfully`), `frontend` (builds `./apps/frontend`, waits for `app`). Named volumes `pgdata` (mounted at `/var/lib/postgresql` — postgres:18 moved it there) and `workspace`. `ANTHROPIC_API_KEY` must be exported or the stack refuses to start. The frontend's `NEXT_PUBLIC_API_URL` build arg defaults to `http://localhost:8000` — correct even in Docker, since the browser calls the backend via its published host port, not the compose network.

## Environment / Secrets

`.envrc` (direnv, repo root) loads `OPENAI_API_KEY` and `SERPER_API_KEY` from the macOS Keychain via `security find-generic-password`; export `ANTHROPIC_API_KEY` yourself (or add it there the same way). Run `direnv allow` once to activate, or set these vars manually on other platforms. direnv loads `.envrc` for the whole repo tree, so it applies whether you're working in `apps/backend/` or `apps/frontend/`.
