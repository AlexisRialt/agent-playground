"""HTTP routes, one router per resource."""

from app.api.health import router as health_router
from app.api.jobs import router as jobs_router

__all__ = ["health_router", "jobs_router"]
