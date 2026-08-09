"""Entrypoint: run the FastAPI server with `uv run main.py`."""

import uvicorn

from app.config import settings
from app.logs import setup_logging


def main() -> None:
    # Configure stdout logging before uvicorn starts so job logs match its format.
    setup_logging(settings.log_level)
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
