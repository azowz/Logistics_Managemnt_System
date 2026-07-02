"""Scheduled webhook-delivery retry sweep (Sprint 14, context #21).

Non-destructive companion to the outbox relay. It re-attempts *due* webhook deliveries
(``pending``/``failed`` with ``next_attempt_at <= now``); it never replays or rebuilds the
event store. Tenant correctness mirrors the relay/health sweeps: the tenant list is read
under platform scope, but every delivery is attempted inside that tenant's own RLS-scoped
transaction (``attempt_delivery`` commits). Each delivery is isolated in its own
try/except so one bad row cannot stall the sweep. Delivered/cancelled/skipped and
retry-exhausted deliveries (``next_attempt_at = NULL``) are excluded by ``list_due``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.common.datetime import utcnow
from app.db.session import session_scope
from app.db.tenant import PLATFORM_TENANT_ID
from app.models.enums import WebhookDeliveryStatus
from app.models.integration import WebhookDelivery
from app.observability.logging import get_logger
from app.repositories.integration_repository import WebhookDeliveryRepository
from app.services.integration_service import IntegrationService

logger = get_logger(__name__)


@dataclass(slots=True)
class SweepResult:
    """Summary of one delivery-sweep run (returned for logs/metrics/tests)."""

    tenants: int = 0
    attempted: int = 0
    delivered: int = 0
    failed: int = 0
    errors: int = 0


def _tenants_with_due_deliveries() -> list:
    """Distinct tenant ids owning at least one due delivery (platform scope)."""
    now = utcnow()
    with session_scope(PLATFORM_TENANT_ID) as session:
        rows = session.scalars(
            select(WebhookDelivery.tenant_id)
            .where(
                WebhookDelivery.status.in_(
                    (WebhookDeliveryStatus.PENDING, WebhookDeliveryStatus.FAILED)
                ),
                WebhookDelivery.next_attempt_at.isnot(None),
                WebhookDelivery.next_attempt_at <= now,
            )
            .distinct()
        ).all()
    return list(rows)


def run_webhook_delivery_sweep(*, batch_per_tenant: int = 100, provider=None) -> SweepResult:
    """Attempt every due delivery across all tenants. Idempotent; per-delivery isolated.

    ``provider`` defaults to the process-configured webhook provider (production wires a
    real ``HttpWebhookProvider`` via ``set_webhook_provider``; the default no-network
    provider never fakes success). Returns an aggregate :class:`SweepResult`.
    """
    result = SweepResult()
    for tenant_id in _tenants_with_due_deliveries():
        result.tenants += 1
        # Short read transaction to collect due ids; the actual attempts (which call out
        # over the network) each run in their own transaction so we never hold a DB
        # transaction open across a webhook HTTP call.
        with session_scope(tenant_id) as session:
            due_ids = [
                d.id for d in WebhookDeliveryRepository(session).list_due(limit=batch_per_tenant)
            ]
        for delivery_id in due_ids:
            result.attempted += 1
            try:
                with session_scope(tenant_id) as session:
                    delivery = IntegrationService(session).attempt_delivery(
                        delivery_id, provider=provider
                    )
                if delivery.status == WebhookDeliveryStatus.DELIVERED:
                    result.delivered += 1
                else:
                    result.failed += 1
            except Exception as exc:  # noqa: BLE001 - one delivery must not stall the sweep
                result.errors += 1
                logger.warning(
                    "Webhook delivery sweep: attempt failed",
                    tenant_id=str(tenant_id),
                    delivery_id=str(delivery_id),
                    error=str(exc),
                )

    if result.tenants:
        logger.info(
            "Webhook delivery sweep complete",
            tenants=result.tenants,
            attempted=result.attempted,
            delivered=result.delivered,
            failed=result.failed,
            errors=result.errors,
        )
    return result


__all__ = ["run_webhook_delivery_sweep", "SweepResult"]
