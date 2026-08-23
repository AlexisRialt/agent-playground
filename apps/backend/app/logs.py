"""Stdout logging setup and helpers, built on loguru.

Named `logs` (not `logging`) so it never shadows the stdlib module. Everything
goes to stdout with a compact, human-scannable format; per-job lines are tagged
with a short job id so you can follow one job among several running at once.

Modules log by importing loguru directly (`from loguru import logger`); this
module only owns configuration, the per-job binding, and message previews.
Stdlib logging (uvicorn, httpx, anything else) is routed into loguru too, so a
single sink handles the whole process.
"""

from __future__ import annotations

import logging
import sys

from loguru import logger

_DEFAULT_FORMAT = (
    "<green>{time:HH:mm:ss}</green> <level>{level: <7}</level> "
    "<cyan>{name: <18}</cyan> {extra[job_tag]}<level>{message}</level>"
)

_configured = False


def _formatter(record: dict) -> str:
    """Prefix per-job lines with `[a1b2c3d4] ` and keep everything else aligned."""
    job_id = record["extra"].get("job_id")
    record["extra"]["job_tag"] = f"[{job_id[:8]}] " if job_id else ""
    return _DEFAULT_FORMAT + "\n{exception}"


class _InterceptHandler(logging.Handler):
    """Forwards stdlib logging records (uvicorn, httpx, …) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Carry the stdlib logger's name over ('uvicorn.access', 'httpx', …);
        # loguru would otherwise infer it from this frame.
        logger.patch(lambda r: r.update(name=record.name)).opt(
            exception=record.exc_info
        ).log(level, record.getMessage())


def setup_logging(level: str = "INFO") -> None:
    """Send all logs to stdout. Idempotent — safe to call from several entrypoints."""
    global _configured
    if _configured:
        return
    logger.remove()
    logger.configure(extra={"job_id": "", "job_tag": ""})
    # diagnose=False: tracebacks stay readable and never dump local variables
    # (which hold api keys and full prompts).
    logger.add(
        sys.stdout,
        level=level.upper(),
        format=_formatter,
        colorize=True,
        backtrace=True,
        diagnose=False,
    )

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    # httpx logs one line per outbound request, which is exactly what we want.
    logging.getLogger("httpx").setLevel("INFO")
    logging.getLogger("httpcore").setLevel("WARNING")
    _configured = True


def job_logger(job_id: str):
    """A logger whose lines are all tagged with this job's short id."""
    return logger.bind(job_id=job_id)


def short(text: object, limit: int = 300) -> str:
    """Collapse a value to a single truncated line, for log-friendly previews."""
    s = " ".join(str(text).split())
    return s if len(s) <= limit else f"{s[:limit]}… (+{len(s) - limit} chars)"
