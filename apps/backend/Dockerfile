# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage: resolve the locked dependencies into a self-contained venv.
# The uv image is python:3.14-slim-trixie with uv on top, so the venv it builds
# points at an interpreter that exists at the same path in the runtime stage.
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer: they only re-resolve when the lock
# changes, not on every source edit.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Runtime stage: interpreter + venv + source, nothing else (no uv, no build
# tooling, no dev dependencies).
# ---------------------------------------------------------------------------
FROM python:3.14-slim-trixie AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    AGENT_WORKSPACE=/data/workspace

# Unprivileged: the agent writes files, so it should not do so as root.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /data/workspace \
    && chown -R agent:agent /data

WORKDIR /app

COPY --from=builder --chown=agent:agent /app/.venv /app/.venv
COPY --chown=agent:agent main.py ./
COPY --chown=agent:agent app ./app
COPY --chown=agent:agent alembic.ini ./
COPY --chown=agent:agent alembic ./alembic

USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()"

CMD ["python", "main.py"]
