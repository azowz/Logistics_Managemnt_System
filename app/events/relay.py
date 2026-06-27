"""Transactional-outbox relay (M2).

Polls ``event_store`` for unpublished rows and publishes each through the
:class:`~app.events.bus.EventBus`, giving **at-least-once** delivery with no
dual-write: the event was already committed atomically with its aggregate, so the
relay only moves it onto the bus and stamps ``published_at``.

Tenant correctness: the batch is *read* under the platform scope (it spans all
tenants), but each event is *published* inside its **own transaction scoped to the
event's tenant**, so handler/projection writes are RLS-checked against the right
tenant. A transport failure increments the attempt counter with bounded backoff;
once ``max_publish_attempts`` is exhausted the event is dead-lettered and stamped
published so one poison row cannot stall the relay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select

from app.common.datetime import utcnow
from app.db.session import session_scope
from app.db.tenant import PLATFORM_TENANT_ID
from app.events import metrics
from app.events.bus import EventBus, get_event_bus
from app.events.envelope import EventEnvelope
from app.models.event_store import EventStore
from app.observability.logging import get_logger
from app.repositories.event_store_repository import EventStoreRepository

logger = get_logger(__name__)

_RELAY_CONSUMER = "__outbox_relay__"


@dataclass(slots=True)
class RelayResult:
    """Summary of a single relay run (returned for logs/metrics/tests)."""

    fetched: int = 0
    published: int = 0
    failed: int = 0
    dead_lettered: int = 0


def _publish_backoff_seconds(attempts: int) -> float:
    """Bounded exponential backoff for transport publish retries."""
    return float(min(300, 2 ** max(1, attempts)))


def run_outbox_relay(
    *,
    batch_size: int = 100,
    max_publish_attempts: int = 5,
    bus: Optional[EventBus] = None,
) -> RelayResult:
    """Publish one batch of unpublished events; returns a :class:`RelayResult`."""
    bus = bus or get_event_bus()
    result = RelayResult()

    # --- 1) read the due batch under platform scope (spans all tenants) ---
    pending: list[tuple[EventEnvelope, int]] = []
    with session_scope(PLATFORM_TENANT_ID) as session:
        repo = EventStoreRepository(session)
        rows = repo.fetch_unpublished(limit=batch_size)
        for row in rows:
            pending.append((EventEnvelope.from_record(row), row.publish_attempts))
        depth = session.scalar(
            select(func.count()).select_from(EventStore).where(EventStore.published_at.is_(None))
        )
        metrics.OUTBOX_DEPTH.set(depth or 0)
    result.fetched = len(pending)

    # --- 2) publish each event in its own tenant-scoped transaction ------
    for envelope, prior_attempts in pending:
        try:
            with session_scope(envelope.tenant_id) as session:
                bus.publish(envelope, session=session)
                EventStoreRepository(session).mark_published(envelope.event_id)
            result.published += 1
        except Exception as exc:  # noqa: BLE001 - transport-level failure handling
            metrics.PUBLISH_FAILURES.labels(envelope.event_type).inc()
            attempts = prior_attempts + 1
            with session_scope(envelope.tenant_id) as session:
                repo = EventStoreRepository(session)
                if attempts >= max_publish_attempts:
                    repo.add_dead_letter(
                        event_id=envelope.event_id,
                        tenant_id=envelope.tenant_id,
                        consumer=_RELAY_CONSUMER,
                        event_type=envelope.event_type,
                        payload=envelope.payload,
                        failure_reason=f"publish failed after {attempts} attempts: {exc}",
                        retry_count=attempts,
                        first_failed_at=utcnow(),
                    )
                    repo.mark_published(envelope.event_id)  # stop polling this row
                    result.dead_lettered += 1
                    logger.error(
                        "Outbox publish exhausted; dead-lettered",
                        event_id=str(envelope.event_id), event_type=envelope.event_type,
                        attempts=attempts, error=str(exc),
                    )
                else:
                    repo.record_publish_failure(
                        envelope.event_id,
                        error=str(exc),
                        next_attempt_at=utcnow() + timedelta(seconds=_publish_backoff_seconds(attempts)),
                    )
                    logger.warning(
                        "Outbox publish failed; will retry",
                        event_id=str(envelope.event_id), attempt=attempts, error=str(exc),
                    )
            result.failed += 1

    if result.fetched:
        logger.info(
            "Outbox relay run complete",
            fetched=result.fetched, published=result.published,
            failed=result.failed, dead_lettered=result.dead_lettered,
        )
    return result


__all__ = ["run_outbox_relay", "RelayResult"]
