"""Stdout logging setup and helpers.

Named `logs` (not `logging`) so it never shadows the stdlib module. Everything
goes to stdout with a compact, human-scannable format; per-job lines are tagged
with a short job id so you can follow one job among several running at once.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Send all logs to stdout. Idempotent — safe to call from several entrypoints."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # httpx logs one line per outbound request, which is exactly what we want.
    logging.getLogger("httpx").setLevel("INFO")
    logging.getLogger("httpcore").setLevel("WARNING")
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class JobLogAdapter(logging.LoggerAdapter):
    """Prefixes every line with the job's short id: `[a1b2c3d4] ...`."""

    def process(self, msg, kwargs):
        return f"[{self.extra['job_id'][:8]}] {msg}", kwargs


def job_logger(name: str, job_id: str) -> JobLogAdapter:
    return JobLogAdapter(logging.getLogger(name), {"job_id": job_id})


def short(text: object, limit: int = 300) -> str:
    """Collapse a value to a single truncated line, for log-friendly previews."""
    s = " ".join(str(text).split())
    return s if len(s) <= limit else f"{s[:limit]}… (+{len(s) - limit} chars)"
