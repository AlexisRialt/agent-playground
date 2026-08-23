# agent-playground frontend

A **Next.js job dashboard** for the [`agent-playground`](../../README.md)
backend: submit a task, watch it move through `pending` → `running` →
`completed`/`failed`, and inspect the plan, tool calls, and result as they
come in.

## Requirements

- **Node.js** and npm
- The [backend](../backend/README.md) running and reachable (defaults to
  `http://localhost:8000`)

## Development

```bash
npm install
cp .env.local.example .env.local   # adjust NEXT_PUBLIC_API_URL if needed
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The dashboard polls
`GET /jobs` every ~3s on the list page and `GET /jobs/{id}` every ~2s on a
job's detail page while it's still `pending`/`running`.

## Configuration

| Variable               | Default                 | Description                                    |
| ----------------------- | ------------------------ | ----------------------------------------------- |
| `NEXT_PUBLIC_API_URL`   | `http://localhost:8000`  | Base URL of the backend API. Inlined into the client bundle at build time, so it must be set before `npm run build` / the Docker build, not just at runtime. |

The backend must allow this origin via its `CORS_ORIGINS` setting (defaults to
`http://localhost:3000`, matching `npm run dev`'s default port).

## Project layout

```
src/
  app/
    page.tsx           # job list + submit form
    jobs/[id]/page.tsx # job detail: log, tool calls, result/error
    layout.tsx
  lib/api.ts            # fetch wrappers + types matching the backend's Job.to_dict()
  components/StatusBadge.tsx
```

## Production build

```bash
npm run build
npm start
```

## Docker

Built as part of the repo-root `docker-compose.yml` (`docker compose up
--build` from the repo root brings up db + backend + frontend together). To
build just this image:

```bash
docker build -t agent-playground-frontend \
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 .
docker run -p 3000:3000 agent-playground-frontend
```

## Linting

```bash
npm run lint
```
