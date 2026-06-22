"""Prometheus metrics instrumentation for the Mesaar API.

Exposes:

* :class:`PrometheusMiddleware` -- a Starlette ``BaseHTTPMiddleware`` that
  records request counts and latency histograms, labelled by method, route
  template, and status code.
* :data:`metrics_asgi_app` -- the ``prometheus_client`` ASGI app, mounted at
  ``/metrics`` so a scraper can pull the registry.
* :func:`setup_metrics` -- wires the middleware and the ``/metrics`` mount into
  a FastAPI application when ``settings.prometheus_enabled`` is true.

Cardinality note: HTTP path labels use the *route template* (e.g.
``/v1/drivers/{driver_id}``) rather than the concrete URL, so that high-
cardinality path parameters (uuids) do not explode the metric series count.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, make_asgi_app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from app.observability.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from fastapi import FastAPI
    from starlette.middleware.base import RequestResponseEndpoint

    from app.core.config import Settings

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Metric definitions.
# ---------------------------------------------------------------------------
# These are module-level singletons registered against the default Prometheus
# registry. Defining them at import time (once) is required: re-registering the
# same metric name raises ``ValueError`` from prometheus_client.
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total number of HTTP requests processed, labelled by method/path/status.",
    labelnames=("method", "path", "status"),
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds, labelled by method/path.",
    labelnames=("method", "path"),
    # Buckets tuned for a web API: sub-millisecond is unrealistic, while
    # anything past ~10s is effectively a timeout for our purposes.
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
)


# ASGI app that renders the Prometheus exposition format. Mounted at /metrics.
metrics_asgi_app = make_asgi_app()


def _resolve_route_template(request: Request) -> str:
    """Return the matched route template for ``request``.

    Iterating the app's routes and asking each to ``matches`` the current scope
    yields the parametrised template (``/v1/drivers/{driver_id}``) instead of
    the concrete path, keeping label cardinality bounded. Falls back to the raw
    path when no route matches (e.g. 404s).
    """

    app = request.app
    routes = getattr(app, "routes", None)
    if routes is None:
        return request.url.path

    for route in routes:
        try:
            match, _ = route.matches(request.scope)
        except Exception as exc:  # Defensive: a malformed route must not 500.
            logger.debug("Route match failed during metrics labelling: {err}", err=str(exc))
            continue
        if match == Match.FULL:
            # ``route.path`` is the template string for Mount/Route objects.
            return getattr(route, "path", request.url.path)

    return request.url.path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record per-request Prometheus counters and latency histograms.

    The middleware times the downstream handler, derives a low-cardinality path
    label from the matched route template, and records both a request counter
    (keyed by status code) and a duration histogram. Errors raised by the
    handler are still counted (as HTTP 500) and the latency observed, after
    which the exception is re-raised so the application's exception handlers can
    format the response.
    """

    async def dispatch(
        self, request: Request, call_next: "RequestResponseEndpoint"
    ) -> Response:
        method = request.method
        start = time.perf_counter()
        status_code = 500  # Assume failure until a response is produced.

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # Count the failed request as a 500 and re-raise; the global
            # exception handlers own the actual response shape.
            status_code = 500
            raise
        finally:
            elapsed_seconds = time.perf_counter() - start
            path_label = _resolve_route_template(request)

            # ``finally`` runs for both success and error paths, so metrics are
            # always recorded exactly once per request.
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method, path=path_label
            ).observe(elapsed_seconds)
            HTTP_REQUESTS_TOTAL.labels(
                method=method, path=path_label, status=str(status_code)
            ).inc()


def setup_metrics(app: "FastAPI", settings: "Settings") -> None:
    """Install Prometheus instrumentation on ``app`` when enabled.

    When ``settings.prometheus_enabled`` is true this adds
    :class:`PrometheusMiddleware` and mounts :data:`metrics_asgi_app` at
    ``/metrics``. When disabled it logs and returns without touching the app, so
    deployments that scrape via a sidecar can opt out cleanly.
    """

    if not getattr(settings, "prometheus_enabled", True):
        logger.info("Prometheus metrics disabled via settings; skipping setup.")
        return

    app.add_middleware(PrometheusMiddleware)
    app.mount("/metrics", metrics_asgi_app)

    logger.info(
        "Prometheus metrics enabled (exposition at /metrics, content-type={ctype}).",
        ctype=CONTENT_TYPE_LATEST,
    )


# Re-export a couple of helpers that callers/tests may want without reaching
# into prometheus_client directly.
__all__ = [
    "PrometheusMiddleware",
    "metrics_asgi_app",
    "setup_metrics",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
]
