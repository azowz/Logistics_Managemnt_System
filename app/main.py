"""FastAPI application entry point and composition root.

:func:`create_app` is the application factory. It wires, in order:

1. logging (must be first so subsequent setup logs through the configured sink),
2. the FastAPI instance (title/version/description/OpenAPI tags),
3. CORS + request-context middleware,
4. Prometheus metrics (middleware + ``/metrics`` mount),
5. global exception handlers (uniform ``ErrorResponse`` envelopes),
6. the unversioned health router (root) and the versioned ``/v1`` business router,
7. a lifespan handler that pings Redis on startup (best-effort) and disposes the
   database engine on shutdown.

A module-level ``app = create_app()`` is preserved so ``uvicorn app.main:app``
keeps working. The versioned business routers are mounted under ``/v1``
(ADR-005) with the driver self-service router first, exactly as before.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import health_router
from app.api.middleware.request_context import RequestContextMiddleware
from app.api.v1.router import build_v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import install_exception_handlers
from app.core.redis import redis_ping
from app.db.session import engine
from app.observability.logging import configure_logging, get_logger
from app.observability.metrics import setup_metrics

logger = get_logger(__name__)

# OpenAPI tag metadata for a tidier docs page. Tags referenced by routers that
# do not appear here still render; this only adds descriptions/ordering.
_OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "meta", "description": "Health, liveness, and readiness probes."},
    {"name": "auth", "description": "Authentication and token issuance."},
    {"name": "users", "description": "User account administration."},
    {"name": "drivers", "description": "Driver profiles and fleet assignment."},
    {"name": "driver-self", "description": "Driver self-service endpoints."},
    {"name": "vehicles", "description": "Vehicle/fleet management."},
    {"name": "warehouses", "description": "Warehouse and depot management."},
    {"name": "shipments", "description": "Shipment lifecycle operations."},
    {"name": "equipment", "description": "Equipment & asset lifecycle operations."},
    {"name": "compliance", "description": "Compliance, permits, escorts, and dispatch gating."},
    {"name": "insurance", "description": "Insurance policies and coverage rules."},
    {"name": "claims", "description": "Claim workflow, damage reports, and liability."},
    {"name": "billing", "description": "Quotes, invoices, payments, settlements, payouts, and penalties."},
    {"name": "notifications", "description": "Notification templates, notifications, and delivery tracking."},
]


def _build_lifespan(settings: Settings):
    """Construct the lifespan context manager bound to ``settings``.

    Startup performs a best-effort Redis ping (logged, never fatal) so a
    degraded cache does not prevent the API from booting -- readiness probes,
    not startup, gate traffic. Shutdown disposes the SQLAlchemy engine so pooled
    connections are released cleanly.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting {app} v{version} (environment={env}).",
            app=settings.app_name,
            version=settings.app_version,
            env=settings.environment,
        )
        # Best-effort dependency warm-up; redis_ping logs and never raises.
        if redis_ping():
            logger.info("Redis reachable at startup.")
        else:
            logger.warning("Redis not reachable at startup; continuing (readiness will gate).")

        try:
            yield
        finally:
            # Release pooled DB connections on graceful shutdown.
            try:
                engine.dispose()
                logger.info("Database engine disposed on shutdown.")
            except Exception as exc:  # Defensive: shutdown must not raise.
                logger.error("Error disposing database engine: {error}", error=str(exc))
            logger.info("Shutdown complete for {app}.", app=settings.app_name)

    return lifespan


def create_app() -> FastAPI:
    """Build and return a fully wired :class:`~fastapi.FastAPI` application."""

    settings = get_settings()

    # Configure logging FIRST so every subsequent setup step logs consistently.
    configure_logging(settings)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Land-freight logistics platform API. RBAC via JWT, multi-tenant "
            "request scoping, structured logging, and Prometheus metrics. "
            "See docs/ for ADRs."
        ),
        openapi_tags=_OPENAPI_TAGS,
        debug=settings.debug,
        lifespan=_build_lifespan(settings),
    )

    # --- Middleware -----------------------------------------------------------
    # CORS first (outermost), then request-context so the request id/tenant are
    # established for the duration of handler execution and access logging.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestContextMiddleware)

    # --- Observability --------------------------------------------------------
    # Prometheus middleware + /metrics mount (no-op when disabled in settings).
    setup_metrics(application, settings)

    # --- Error handling -------------------------------------------------------
    # Uniform ErrorResponse envelopes for AppError, validation errors, mapped
    # domain exceptions, and a catch-all.
    install_exception_handlers(application)

    # --- Routes ---------------------------------------------------------------
    # Health endpoints at the root (unversioned) for orchestrator probes.
    application.include_router(health_router)
    # Versioned business surface under settings.api_v1_prefix (/v1).
    application.include_router(build_v1_router())

    logger.info(
        "Application assembled (cors_origins={cors}, metrics={metrics}).",
        cors=settings.cors_origins,
        metrics=settings.prometheus_enabled,
    )
    return application


# Module-level app so ``uvicorn app.main:app`` continues to work.
app = create_app()


__all__ = ["app", "create_app"]
