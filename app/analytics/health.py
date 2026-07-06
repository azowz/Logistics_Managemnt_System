"""Scheduled projection-health sweep (Sprint 12, context #20).

Non-destructive companion to the outbox relay. Where the relay *moves* events onto
the bus, this sweep only *inspects* the resulting projections: for every tenant that
has projection-health rows it asks :meth:`ProjectionService.run_health_check` to
re-classify each projection as ``healthy`` / ``stale`` (it never replays or rebuilds,
so it cannot corrupt a read model or mutate the event backbone). Staleness is advisory
— surfaced through the analytics health endpoint so operators decide when a rebuild is
warranted.

Tenant correctness mirrors the relay: the tenant list is read under platform scope,
but each tenant's health rows are updated inside that tenant's own RLS-scoped
transaction. A failure for one tenant is logged and skipped so it cannot stall the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import session_scope
from app.db.tenant import PLATFORM_TENANT_ID
from app.models.projection import ProjectionHealth
from app.observability.logging import get_logger
from app.services.projection_service import ProjectionService

logger = get_logger(__name__)


@dataclass(slots=True)
class HealthCheckResult:
    """Summary of one health-sweep run (returned for logs/metrics/tests)."""

    tenants: int = 0
    checked: int = 0
    healthy: int = 0
    stale: int = 0
    error: int = 0


def _distinct_tenant_ids() -> list:
    """Tenant ids that own at least one projection-health row (platform scope)."""
    with session_scope(PLATFORM_TENANT_ID) as session:
        rows = session.scalars(select(ProjectionHealth.tenant_id).distinct()).all()
    return list(rows)


def run_projection_health_check() -> HealthCheckResult:
    """Sweep every tenant's projection-health rows and re-classify staleness.

    Idempotent and side-effect-bounded: it writes only to ``projection_health`` and
    each tenant is committed independently. Returns an aggregate :class:`HealthCheckResult`.
    """
    result = HealthCheckResult()
    for tenant_id in _distinct_tenant_ids():
        result.tenants += 1
        try:
            with session_scope(tenant_id) as session:
                summary = ProjectionService(session).run_health_check(tenant_id)
            result.checked += summary["checked"]
            result.healthy += summary["healthy"]
            result.stale += summary["stale"]
            result.error += summary["error"]
        except Exception as exc:  # noqa: BLE001 - one tenant must not stall the sweep
            logger.warning(
                "Projection health check failed for tenant; continuing",
                tenant_id=str(tenant_id),
                error=str(exc),
            )

    if result.tenants:
        logger.info(
            "Projection health sweep complete",
            tenants=result.tenants,
            checked=result.checked,
            healthy=result.healthy,
            stale=result.stale,
            error=result.error,
        )
    return result


__all__ = ["run_projection_health_check", "HealthCheckResult"]
