"""Entrypoint: run the FastAPI server with `uv run main.py`."""

import uvicorn

from app.config import settings
from app.logs import setup_logging


def main() -> None:
    # Configure loguru before uvicorn starts so its logs come out in our format too.
    setup_logging(settings.log_level)
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level=settings.log_level.lower(),
        # Don't let uvicorn install its own handlers — its loggers propagate to
        # the root InterceptHandler and come out through loguru instead.
        log_config=None,
    )


if __name__ == "__main__":
    main()
