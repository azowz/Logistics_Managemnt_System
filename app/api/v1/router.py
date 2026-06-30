"""Assembly of the versioned ``/v1`` API surface.

This module composes the EXISTING business routers (located in
``app.api.routes``) into a single :class:`fastapi.APIRouter` mounted under the
configured ``api_v1_prefix`` (``/v1`` by ADR-005).

Router ordering is load-bearing and MUST match the historical wiring: the
driver self-service router is included FIRST so its specific paths
(``/drivers/me``, ``/shipments/nearby``, ``/shipments/{id}/accept``) take
precedence over the generic ``/drivers/{id}`` and ``/shipments/{id}`` routes.
The remaining order is: auth, users, drivers, vehicles, warehouses, shipments.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    auth,
    compliance,
    customers,
    driver_self,
    drivers,
    equipment,
    orders,
    shipments,
    users,
    vehicles,
    warehouses,
)
from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)


def build_v1_router() -> APIRouter:
    """Build and return the versioned ``/v1`` router.

    The prefix is read from :class:`~app.core.config.Settings` so it can be
    overridden per environment, while defaulting to ``/v1``. The inclusion order
    is preserved exactly as in the legacy ``app.main`` wiring (driver_self
    first); changing it would silently reroute driver-specific endpoints to the
    generic ``{id}`` handlers.

    Returns
    -------
    APIRouter
        A router carrying every business endpoint under ``settings.api_v1_prefix``.
    """

    settings = get_settings()
    router = APIRouter(prefix=settings.api_v1_prefix)

    # Specific driver-self paths first so they win over generic ``{id}`` routes.
    router.include_router(driver_self.router)
    router.include_router(auth.router)
    router.include_router(users.router)
    router.include_router(drivers.router)
    router.include_router(vehicles.router)
    router.include_router(warehouses.router)
    router.include_router(shipments.router)
    router.include_router(customers.router)
    router.include_router(orders.router)
    router.include_router(equipment.router)
    router.include_router(compliance.router)

    logger.info(
        "Built v1 API router (prefix={prefix}, routers=11).",
        prefix=settings.api_v1_prefix,
    )
    return router


__all__ = ["build_v1_router"]
