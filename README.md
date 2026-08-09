# agent-playground

A small **FastAPI server that runs Claude-powered agent jobs**. You submit a text
task, the server runs a [Claude](https://www.anthropic.com/) agent in the background,
and you poll for the plan, the tool calls it made, and the final result.

The agent has exactly **two tools**:

- **filesystem** — read/write/list files inside a private, sandboxed workspace.
- **google_search** — search Google for up-to-date information (via [SerpAPI](https://serpapi.com)).

Given a task, the agent first writes a short **plan**, then decides what to do —
searching the web and/or persisting files — until it produces an answer.

## Requirements

- **Python >= 3.14**
- [uv](https://docs.astral.sh/uv/) for dependency and environment management
- An **Anthropic API key** (`ANTHROPIC_API_KEY`)
- *(optional)* a **SerpAPI key** (`SERPER_API_KEY`) to enable live Google
  results — without it, the search tool returns a clear "not configured" message
  and everything else still works.

## Setup

Install dependencies:

```bash
uv sync
```

Provide your Anthropic API key. On macOS this repo's `.envrc` (via
[direnv](https://direnv.net/)) loads it from the Keychain:

```bash
direnv allow
```

Or set it manually on any platform:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export SERPER_API_KEY=...   # optional, enables live Google search
```

## Running the server

```bash
uv run main.py
```

The server starts on **http://127.0.0.1:8000**.

### Swagger UI (interactive API docs)

FastAPI serves interactive API docs automatically — no extra setup:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc
- **OpenAPI schema (JSON):** http://127.0.0.1:8000/openapi.json

Open `/docs` in a browser to submit jobs and inspect responses right from the page:
expand **POST /jobs**, click **Try it out**, edit the request body, and **Execute**.

## API

| Method | Path            | Description                                              |
| ------ | --------------- | -------------------------------------------------------- |
| POST   | `/jobs`         | Submit a task; returns a job id and starts the agent.    |
| GET    | `/jobs/{id}`    | Poll a job's status, plan/log, tool calls, and result.   |
| GET    | `/jobs`         | List all jobs (summaries).                               |
| GET    | `/healthz`      | Liveness check.                                          |

### Submit a job

```bash
curl -X POST localhost:8000/jobs \
  -H 'content-type: application/json' \
  -d '{"text":"Find the latest stable Python version and write a one-paragraph summary to summary.md"}'
```

Response (`202 Accepted`):

```json
{ "id": "31f97170bd3745afb1d65270fddf7a75", "status": "pending" }
```

### Poll for the result

```bash
curl localhost:8000/jobs/31f97170bd3745afb1d65270fddf7a75
```

Response:

```json
{
  "id": "31f97170bd3745afb1d65270fddf7a75",
  "status": "completed",
  "task": "Find the latest stable Python version and write ...",
  "log": ["Plan:\n1. Search for the latest ...", "..."],
  "tool_calls": [
    { "tool": "google_search", "input": { "query": "latest stable Python version" }, "output": "...", "is_error": false, "at": "..." },
    { "tool": "filesystem", "input": { "command": "write", "path": "summary.md", "content": "..." }, "output": "wrote 412 characters to summary.md", "is_error": false, "at": "..." }
  ],
  "result": "The latest stable Python release is ... I saved a summary to summary.md.",
  "error": null,
  "created_at": "...",
  "updated_at": "..."
}
```

`status` moves `pending` → `running` → `completed` (or `failed`, with the reason in `error`).

Any files the agent creates land in `workspace/<job_id>/`.

## Configuration

All settings are environment variables with sensible defaults (see
[app/config.py](app/config.py)):

| Variable                 | Default            | Description                                             |
| ------------------------ | ------------------ | ------------------------------------------------------- |
| `ANTHROPIC_API_KEY`      | *(required)*       | Anthropic API key (read by the SDK directly).           |
| `SERPER_API_KEY`         | *(unset)*          | SerpAPI key; enables live Google search.                |
| `AGENT_MODEL`            | `claude-opus-4-8`  | Claude model the agent uses.                            |
| `AGENT_EFFORT`           | `high`             | Reasoning effort: `low`/`medium`/`high`/`xhigh`/`max`.  |
| `AGENT_MAX_ITERATIONS`   | `20`               | Max tool-use round-trips before the loop gives up.      |
| `AGENT_MAX_TOKENS`       | `16000`            | Per-response output token cap.                          |
| `AGENT_WORKSPACE`        | `workspace`        | Root directory for per-job file sandboxes.              |

## Project layout

```
main.py            # uvicorn launcher (uv run main.py)
app/
  main.py          # FastAPI app + routes; background job execution
  agent.py         # the Claude tool-use loop (plan, then act)
  jobs.py          # in-memory job store and records
  config.py        # env-driven settings
  tools/
    filesystem.py  # sandboxed read/write/list tool
    search.py      # google_search tool (SerpAPI)
```

> **Note:** the job store is in-memory, so jobs are lost when the server restarts.
> Swap in Redis or a database for durability.

## Development

```bash
uv run ruff check .      # lint (add --fix to autofix)
uv run ruff format .     # format
uv run pytest            # tests (none yet)
```

my search engine: 

<script async src="https://cse.google.com/cse.js?cx=e17ac352d6ea543e8">
</script>
<div class="gcse-search"></div>