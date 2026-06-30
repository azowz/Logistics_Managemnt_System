"""Configured Celery application for the Mesaar logistics platform.

This module builds the singleton :data:`celery_app` used by both the worker
processes and any code that needs to enqueue tasks. Configuration is sourced
entirely from :func:`app.core.config.get_settings` so broker/backend URLs and
retry policy stay environment-driven.

Operational choices:
    * ``task_acks_late`` + ``worker_prefetch_multiplier=1`` give at-least-once
      semantics with fair dispatch -- tasks must therefore be idempotent.
    * ``task_track_started`` surfaces a STARTED state for observability.
    * Hard and soft time limits bound runaway tasks.
    * JSON-only serialization avoids pickle-related security pitfalls.
    * UTC timezone keeps scheduling consistent with the rest of the platform.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready

from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Settings are resolved at import time so the broker/backend are wired up
# before the worker bootstraps. get_settings() is cached, so this is cheap.
settings = get_settings()

# Hard and soft execution limits (seconds). The soft limit raises
# SoftTimeLimitExceeded inside the task so it can clean up before the hard kill.
_TASK_TIME_LIMIT_SECONDS = 300
_TASK_SOFT_TIME_LIMIT_SECONDS = 270

celery_app = Celery(
    "mesaar",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Reliability: ack after completion and only prefetch one task at a time so
    # a crashed worker re-queues rather than silently drops work.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    # Bound task execution time.
    task_time_limit=_TASK_TIME_LIMIT_SECONDS,
    task_soft_time_limit=_TASK_SOFT_TIME_LIMIT_SECONDS,
    # Retry policy default; individual tasks may override countdown.
    task_default_retry_delay=settings.celery_task_default_retry_delay,
    # Safe, interoperable serialization.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Time handling.
    timezone="UTC",
    enable_utc=True,
    # Result lifecycle: expire stored results after one hour to bound backend growth.
    result_expires=3600,
    # Routing / scheduling.
    task_routes={},
    beat_schedule={
        # Transactional-outbox relay: runs every 30 s so event lag stays low
        # (ADR-007; relay is idempotent and safe to run concurrently).
        "relay-outbox-every-30s": {
            "task": "mesaar.relay_outbox",
            "schedule": 30.0,
            "args": [],
            "kwargs": {"batch_size": 100},
            "options": {"expires": 25},  # discard if previous is still running
        },
        # Projection-health sweep: every 5 min, re-classify projection staleness.
        # Non-destructive (never replays/rebuilds), idempotent, and overlap-guarded.
        "projection-health-check-every-5m": {
            "task": "mesaar.projection_health_check",
            "schedule": 300.0,
            "args": [],
            "kwargs": {},
            "options": {"expires": 280},  # discard if previous is still running
        },
    },
)


@worker_ready.connect
def _on_worker_ready(sender: object = None, **_kwargs: object) -> None:
    """Log a structured message once a worker has fully initialized.

    Args:
        sender: The worker consumer instance Celery passes to the signal.
        **_kwargs: Additional signal arguments (ignored).
    """
    hostname = getattr(sender, "hostname", "unknown")
    logger.info(
        "Celery worker ready",
        extra={
            "hostname": hostname,
            "broker": settings.celery_broker_url,
            "backend": settings.celery_result_backend,
        },
    )


__all__ = ["celery_app"]
