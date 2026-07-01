"""Diagnostic Celery tasks for the Mesaar logistics platform.

This module intentionally contains NO business logic. It provides a single
idempotent ``ping`` task used to verify that the broker, worker, and result
backend are wired together correctly, and to demonstrate the standard retry
pattern used across the platform.
"""

from __future__ import annotations

from celery import Task
from kombu.exceptions import OperationalError

from app.core.config import get_settings
from app.core.redis import redis_ping
from app.observability.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

settings = get_settings()


class _TransientPingError(RuntimeError):
    """Raised when the ping task hits a recoverable infrastructure failure.

    Used to trigger Celery's retry machinery for transient conditions (e.g.,
    Redis temporarily unreachable) rather than failing the task outright.
    """


@celery_app.task(
    bind=True,
    name="mesaar.ping",
    max_retries=settings.celery_task_max_retries,
)
def ping(self: Task) -> str:
    """Return ``"pong"`` after verifying basic infrastructure reachability.

    This task is idempotent and side-effect free. It performs a best-effort
    Redis reachability check to exercise the dependency graph; if Redis is not
    reachable it demonstrates the canonical retry pattern by re-scheduling
    itself with a bounded countdown.

    Args:
        self: The bound :class:`celery.Task` instance (``bind=True``).

    Returns:
        The literal string ``"pong"`` on success.

    Raises:
        celery.exceptions.Retry: When a transient failure is detected and
            retries remain.
        _TransientPingError: When retries are exhausted for a transient failure.
    """
    try:
        # Touch Redis to confirm the broker/backend infrastructure is alive.
        # redis_ping never raises, so an unreachable Redis surfaces as ``False``.
        if not redis_ping():
            raise _TransientPingError("Redis is not reachable")

        logger.info(
            "Ping task succeeded",
            extra={"task_id": self.request.id, "retries": self.request.retries},
        )
        return "pong"
    except (_TransientPingError, OperationalError) as exc:
        # Transient infrastructure failure: retry with the configured backoff
        # until max_retries is exhausted, at which point Celery re-raises.
        countdown = settings.celery_task_default_retry_delay
        logger.warning(
            "Ping task hit a transient failure; scheduling retry",
            extra={
                "task_id": self.request.id,
                "retries": self.request.retries,
                "max_retries": self.max_retries,
                "countdown": countdown,
                "error": str(exc),
            },
        )
        raise self.retry(exc=exc, countdown=countdown)


@celery_app.task(name="mesaar.relay_outbox")
def relay_outbox(batch_size: int = 100) -> dict[str, int]:
    """Publish one batch of unpublished events from the transactional outbox.

    Thin wrapper over :func:`app.events.relay.run_outbox_relay` (the worker layer
    holds no business logic). Intended to be scheduled on a short celery-beat
    interval; each run is idempotent and safe to overlap-guard at the scheduler.

    Returns:
        A summary dict ``{fetched, published, failed, dead_lettered}``.
    """
    # Imported lazily so the event backbone (and its SQLAlchemy models) are not
    # imported at worker module load unless the task actually runs.
    from app.events.relay import run_outbox_relay

    result = run_outbox_relay(batch_size=batch_size)
    return {
        "fetched": result.fetched,
        "published": result.published,
        "failed": result.failed,
        "dead_lettered": result.dead_lettered,
    }


@celery_app.task(name="mesaar.projection_health_check")
def projection_health_check() -> dict[str, int]:
    """Run one non-destructive projection-health sweep across all tenants.

    Thin wrapper over :func:`app.analytics.health.run_projection_health_check` (the
    worker layer holds no business logic). Re-classifies projection staleness only; it
    never replays events or rebuilds projections, so it is safe to overlap-guard at the
    scheduler and idempotent across runs.

    Returns:
        A summary dict ``{tenants, checked, healthy, stale, error}``.
    """
    # Lazy import keeps the analytics/SQLAlchemy stack out of worker module load.
    from app.analytics.health import run_projection_health_check

    result = run_projection_health_check()
    return {
        "tenants": result.tenants,
        "checked": result.checked,
        "healthy": result.healthy,
        "stale": result.stale,
        "error": result.error,
    }


@celery_app.task(name="mesaar.webhook_delivery_sweep")
def webhook_delivery_sweep(batch_per_tenant: int = 100) -> dict[str, int]:
    """Attempt one batch of due webhook deliveries across all tenants.

    Thin wrapper over :func:`app.integrations.sweep.run_webhook_delivery_sweep` (the worker
    layer holds no business logic). Non-destructive (never replays/rebuilds the event
    store), idempotent, per-delivery isolated, and safe to overlap-guard at the scheduler.

    Returns:
        A summary dict ``{tenants, attempted, delivered, failed, errors}``.
    """
    # Lazy import keeps the integration/SQLAlchemy stack off worker module load.
    from app.integrations.sweep import run_webhook_delivery_sweep

    result = run_webhook_delivery_sweep(batch_per_tenant=batch_per_tenant)
    return {
        "tenants": result.tenants,
        "attempted": result.attempted,
        "delivered": result.delivered,
        "failed": result.failed,
        "errors": result.errors,
    }


__all__ = ["ping", "relay_outbox", "projection_health_check", "webhook_delivery_sweep"]
