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


__all__ = ["ping"]
