# agent-playground

A monorepo for experimenting with LLM agents:

- **[`apps/backend`](apps/backend/README.md)** — a FastAPI server that runs
  [Claude](https://www.anthropic.com/)-powered agent jobs. Submit a text task,
  the server runs an agent in the background (with a sandboxed filesystem and
  Google search as its only tools), and you poll for the plan, tool calls, and
  result. Jobs persist in PostgreSQL.
- **[`apps/frontend`](apps/frontend/README.md)** — a Next.js dashboard for
  submitting jobs and watching them run.

## Quick start (whole stack)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export SERPER_API_KEY=...          # optional, enables live Google search
docker compose up --build
```

- Dashboard: **http://localhost:3000**
- API + docs: **http://localhost:8000** (`/docs` for Swagger UI)
- Postgres: `localhost:5432` (`agent`/`agent`/`agent`)

See each app's README for running it standalone (without Docker), the full
API/config reference, and development commands (tests, lint).

## Layout

```
apps/
  backend/    # FastAPI + Claude agent server (Python, uv)
  frontend/   # Next.js job dashboard (TypeScript, npm)
docker-compose.yml  # db + backend + frontend
CLAUDE.md           # guidance for Claude Code working in this repo
```
