"""Observability package: structured logging, metrics, and health checks.

This package provides cross-cutting operational concerns for the Mesaar
logistics platform:

* :mod:`app.observability.logging` -- loguru-based structured logging with
  stdlib/uvicorn interception and request-id context propagation.
* :mod:`app.observability.metrics` -- Prometheus middleware and the
  ``/metrics`` ASGI endpoint.
* :mod:`app.observability.health` -- database/redis health probes and an
  aggregated readiness report.

Import discipline (to avoid import cycles):
    ``logging`` must NOT import ``metrics`` or ``health``. The latter two may
    import ``logging`` to obtain a logger.
"""

from __future__ import annotations

__all__ = [
    "logging",
    "metrics",
    "health",
]
