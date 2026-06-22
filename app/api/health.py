"""Health, liveness, and readiness probes (unversioned, mounted at root).

These endpoints are intentionally NOT placed under the ``/v1`` prefix: orchestra-
tors (Kubernetes, load balancers) probe stable, version-independent paths.

* ``GET /health``      -- overall health snapshot (always 200 when the process
  can serve requests; includes downstream check summary).
* ``GET /health/live`` -- liveness: returns 200 as long as the process is up.
  It deliberately performs NO downstream I/O so a transient DB/Redis outage does
  not cause the orchestrator to kill (restart) an otherwise-healthy pod.
* ``GET /health/ready``-- readiness: aggregates downstream checks via
  :func:`app.observability.health.readiness`; returns 200 when all checks pass,
  otherwise 503 so traffic is drained until dependencies recover.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.common.datetime import utcnow
from app.core.config import get_settings
from app.observability.health import readiness
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Unversioned router mounted at the application root.
health_router = APIRouter(tags=["meta"])


@health_router.get("/health", summary="Overall health snapshot.")
def health() -> dict[str, Any]:
    """Return a combined liveness + readiness snapshot.

    Always responds 200 (the process is clearly able to serve this request).
    The body embeds the downstream readiness aggregate so a single human-
    friendly call surfaces both "am I up" and "are my dependencies healthy".
    """

    settings = get_settings()
    checks = readiness()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "timestamp": utcnow().isoformat(),
        "readiness": checks,
    }


@health_router.get("/health/live", summary="Liveness probe.")
def liveness() -> dict[str, str]:
    """Liveness check: 200 whenever the process is running.

    No downstream dependencies are touched on purpose -- liveness answers only
    "is the process alive", so a dependency outage must not trigger a restart.
    """

    return {"status": "ok"}


@health_router.get("/health/ready", summary="Readiness probe.")
def readiness_probe(response: Response) -> dict[str, Any]:
    """Readiness check aggregating downstream dependency health.

    Delegates to :func:`app.observability.health.readiness`, which inspects the
    database and Redis and never raises. When the aggregate status is not
    ``"ok"`` the HTTP status is set to 503 so load balancers drain traffic until
    the dependencies recover.
    """

    checks = readiness()
    if checks.get("status") != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning("Readiness probe reporting NOT READY: {checks}", checks=checks)
    return checks


__all__ = ["health_router"]
