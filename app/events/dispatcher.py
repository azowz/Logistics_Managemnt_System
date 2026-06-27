"""Idempotent event dispatch with bounded retry and dead-lettering (M2).

The :class:`Dispatcher` delivers a single :class:`~app.events.envelope.EventEnvelope`
to a single consumer with effectively-once semantics:

1. **Idempotency** — if ``(consumer, event_id)`` is already in ``processed_events``
   the delivery is skipped.
2. **Isolation** — the handler runs inside a SAVEPOINT so a failure rolls back only
   that handler's writes, never the surrounding batch.
3. **Retry** — transient failures are retried with bounded exponential backoff.
4. **Dead-letter** — once retries are exhausted the event is written to
   ``dead_letter_events`` and dispatch returns without raising, so one poison
   message cannot stall the stream.

``mark_processed`` and the DLQ write share the caller's (relay's) transaction, so
the projection write + the idempotency record commit atomically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.events import metrics
from app.events.envelope import EventEnvelope
from app.events.registry import EventRegistry, event_registry
from app.observability.logging import get_logger
from app.repositories.event_store_repository import EventStoreRepository

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from app.events.bus import EventHandler

logger = get_logger(__name__)

# Dispatch results (also used to tally a publish across many handlers).
PROCESSED = "processed"
SKIPPED = "skipped"
DEAD_LETTERED = "dead_lettered"


def compute_backoff(attempt: int, *, base: float = 0.2, cap: float = 5.0) -> float:
    """Return bounded exponential backoff seconds for a 1-based ``attempt``."""
    return min(cap, base * (2 ** (attempt - 1)))


@dataclass(slots=True)
class DispatchOutcome:
    """Tally of a publish fanned out across all subscribed handlers."""

    processed: int = 0
    skipped: int = 0
    dead_lettered: int = 0

    def record(self, result: str) -> None:
        if result == PROCESSED:
            self.processed += 1
        elif result == SKIPPED:
            self.skipped += 1
        elif result == DEAD_LETTERED:
            self.dead_lettered += 1


class Dispatcher:
    """Delivers an envelope to one consumer idempotently, with retry + DLQ."""

    def __init__(
        self,
        session: Session,
        *,
        max_retries: int = 3,
        registry: EventRegistry | None = None,
        repo: EventStoreRepository | None = None,
        sleep=time.sleep,
    ) -> None:
        self._session = session
        self._repo = repo or EventStoreRepository(session)  # injectable for tests
        self._max_retries = max_retries
        self._registry = registry or event_registry
        self._sleep = sleep  # injectable so tests don't actually wait

    def dispatch(self, handler: "EventHandler", envelope: EventEnvelope) -> str:
        """Deliver ``envelope`` to ``handler`` exactly once; never raises on handler error."""
        consumer = handler.name
        etype = envelope.event_type

        if self._repo.is_processed(consumer, envelope.event_id):
            metrics.EVENTS_SKIPPED.labels(etype, consumer).inc()
            return SKIPPED

        # Deserialize (with upcasting) once; a bad payload is a permanent failure.
        try:
            event = self._registry.deserialize(envelope)
        except Exception as exc:  # noqa: BLE001 - normalize to a dead-letter
            logger.error("Undeserializable event; dead-lettering", event_id=str(envelope.event_id), error=str(exc))
            self._dead_letter(envelope, consumer, reason=f"deserialize: {exc}", retry_count=0, first_failed=utcnow())
            return DEAD_LETTERED

        attempt = 0
        first_failed = None
        while True:
            try:
                with metrics.DISPATCH_LATENCY.labels(etype, consumer).time():
                    # SAVEPOINT: isolate the handler's writes from the batch.
                    with self._session.begin_nested():
                        handler.handle(event, envelope, self._session)
                self._repo.mark_processed(consumer, envelope.event_id)
                metrics.EVENTS_PROCESSED.labels(etype, consumer).inc()
                return PROCESSED
            except Exception as exc:  # noqa: BLE001 - retry/DLQ policy below
                attempt += 1
                first_failed = first_failed or utcnow()
                metrics.EVENTS_FAILED.labels(etype, consumer).inc()
                if attempt > self._max_retries:
                    logger.error(
                        "Handler exhausted retries; dead-lettering",
                        consumer=consumer, event_id=str(envelope.event_id),
                        event_type=etype, attempts=attempt, error=str(exc),
                    )
                    self._dead_letter(
                        envelope, consumer, reason=str(exc),
                        retry_count=attempt - 1, first_failed=first_failed,
                    )
                    return DEAD_LETTERED
                metrics.EVENTS_RETRIED.labels(etype, consumer).inc()
                logger.warning(
                    "Handler failed; retrying",
                    consumer=consumer, event_id=str(envelope.event_id),
                    attempt=attempt, error=str(exc),
                )
                self._sleep(compute_backoff(attempt))

    def _dead_letter(self, envelope, consumer, *, reason, retry_count, first_failed) -> None:
        self._repo.add_dead_letter(
            event_id=envelope.event_id,
            tenant_id=envelope.tenant_id,
            consumer=consumer,
            event_type=envelope.event_type,
            payload=envelope.payload,
            failure_reason=reason,
            retry_count=retry_count,
            first_failed_at=first_failed,
        )
        # Record as processed so we don't re-deliver a known-poison message; the
        # DLQ row is the durable record for diagnosis/replay.
        self._repo.mark_processed(consumer, envelope.event_id)
        metrics.EVENTS_DEAD_LETTERED.labels(envelope.event_type, consumer).inc()


__all__ = ["Dispatcher", "DispatchOutcome", "compute_backoff", "PROCESSED", "SKIPPED", "DEAD_LETTERED"]
