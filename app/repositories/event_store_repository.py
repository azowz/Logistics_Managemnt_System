"""Persistence boundary for the event backbone (M2).

Owns reads/writes of ``event_store`` (append + transactional-outbox columns),
``processed_events`` (idempotency), ``dead_letter_events`` (DLQ), and the
Layer-3 ``audit_log`` rows that mirror every appended domain event.

The repository never decides *whether* to emit an event (that is the owning
aggregate's service); it persists what it is given, within the caller's unit of
work, and surfaces the optimistic-concurrency collision as a typed error.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.events.envelope import EventEnvelope
from app.events.exceptions import ConcurrencyConflictError
from app.models.audit_log import AuditLog
from app.models.event_store import DeadLetterEvent, EventStore, ProcessedEvent
from app.observability.logging import get_logger

logger = get_logger(__name__)


class EventStoreRepository:
    """CRUD + replay/outbox/idempotency queries over the event backbone tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ---- append (write side) ------------------------------------------
    def append(self, envelope: EventEnvelope, *, write_audit: bool = True) -> EventStore:
        """Append an event to the store within the caller's transaction.

        Sets ``next_attempt_at`` so the outbox relay picks the row up immediately.
        A duplicate ``(aggregate_id, aggregate_version)`` raises
        :class:`ConcurrencyConflictError` (the optimistic-concurrency signal).
        Also writes the Layer-3 audit row unless ``write_audit`` is False.
        """
        record = EventStore(**envelope.to_record(), next_attempt_at=utcnow())
        self._session.add(record)
        if write_audit:
            self._session.add(
                AuditLog(
                    tenant_id=envelope.tenant_id,
                    table_name=envelope.aggregate_type,
                    row_id=envelope.aggregate_id,
                    action="E",
                    new_row=envelope.payload,
                    actor_user_id=envelope.user_id,
                    event_id=envelope.event_id,
                    at=envelope.occurred_at,
                )
            )
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning(
                "Optimistic-concurrency conflict appending event",
                aggregate_type=envelope.aggregate_type,
                aggregate_id=str(envelope.aggregate_id),
                aggregate_version=envelope.aggregate_version,
            )
            raise ConcurrencyConflictError(
                f"{envelope.aggregate_type} {envelope.aggregate_id} "
                f"version {envelope.aggregate_version} already exists"
            ) from exc
        return record

    def next_aggregate_version(self, aggregate_id: uuid.UUID) -> int:
        """Return the next ``aggregate_version`` for an aggregate (max + 1, else 1).

        Convenience for emitters not tracking the aggregate's ``version`` column;
        the unique constraint remains the authoritative race guard.
        """
        stmt = (
            select(EventStore.aggregate_version)
            .where(EventStore.aggregate_id == aggregate_id)
            .order_by(EventStore.aggregate_version.desc())
            .limit(1)
        )
        current = self._session.scalars(stmt).first()
        return (current or 0) + 1

    # ---- outbox (relay side) ------------------------------------------
    def fetch_unpublished(
        self, *, limit: int = 100, now: Optional[datetime] = None
    ) -> Sequence[EventStore]:
        """Return due, unpublished events ordered by time (FIFO-ish via UUIDv7)."""
        now = now or utcnow()
        stmt = (
            select(EventStore)
            .where(
                EventStore.published_at.is_(None),
                (EventStore.next_attempt_at.is_(None)) | (EventStore.next_attempt_at <= now),
            )
            .order_by(EventStore.occurred_at, EventStore.event_id)
            .limit(limit)
        )
        return self._session.scalars(stmt).all()

    def mark_published(
        self, event_id: uuid.UUID, *, published_at: Optional[datetime] = None
    ) -> None:
        """Stamp ``published_at`` so the relay stops considering this row."""
        record = self._session.get(EventStore, event_id)
        if record is not None:
            record.published_at = published_at or utcnow()
            record.last_error = None

    def record_publish_failure(
        self, event_id: uuid.UUID, *, error: str, next_attempt_at: datetime
    ) -> int:
        """Increment the attempt counter + schedule a retry; return new attempt count."""
        record = self._session.get(EventStore, event_id)
        if record is None:  # pragma: no cover - defensive
            return 0
        record.publish_attempts += 1
        record.last_error = error[:2000]
        record.next_attempt_at = next_attempt_at
        return record.publish_attempts

    # ---- dead letter ---------------------------------------------------
    def add_dead_letter(
        self,
        *,
        event_id: uuid.UUID,
        tenant_id: uuid.UUID,
        consumer: str,
        event_type: str,
        payload: dict,
        failure_reason: str,
        retry_count: int,
        first_failed_at: datetime,
        last_failed_at: Optional[datetime] = None,
    ) -> DeadLetterEvent:
        """Record an exhausted-retry event for later diagnosis/replay."""
        dlq = DeadLetterEvent(
            event_id=event_id,
            tenant_id=tenant_id,
            consumer=consumer,
            event_type=event_type,
            payload=payload,
            failure_reason=failure_reason[:4000],
            retry_count=retry_count,
            first_failed_at=first_failed_at,
            last_failed_at=last_failed_at or utcnow(),
        )
        self._session.add(dlq)
        return dlq

    # ---- idempotency (consumer side) ----------------------------------
    def is_processed(self, consumer: str, event_id: uuid.UUID) -> bool:
        """Return True if ``consumer`` already handled ``event_id``."""
        return (
            self._session.get(ProcessedEvent, {"consumer": consumer, "event_id": event_id})
            is not None
        )

    def mark_processed(self, consumer: str, event_id: uuid.UUID) -> None:
        """Record that ``consumer`` handled ``event_id`` (idempotent)."""
        if not self.is_processed(consumer, event_id):
            self._session.add(ProcessedEvent(consumer=consumer, event_id=event_id))

    # ---- replay (read side) -------------------------------------------
    def replay_by_aggregate(
        self, aggregate_type: str, aggregate_id: uuid.UUID
    ) -> Sequence[EventStore]:
        """All events for one aggregate, in ``aggregate_version`` order."""
        stmt = (
            select(EventStore)
            .where(
                EventStore.aggregate_type == aggregate_type,
                EventStore.aggregate_id == aggregate_id,
            )
            .order_by(EventStore.aggregate_version)
        )
        return self._session.scalars(stmt).all()

    def replay_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> Sequence[EventStore]:
        """All events for a tenant within an optional time window, time-ordered."""
        stmt = select(EventStore).where(EventStore.tenant_id == tenant_id)
        if since is not None:
            stmt = stmt.where(EventStore.occurred_at >= since)
        if until is not None:
            stmt = stmt.where(EventStore.occurred_at < until)
        stmt = stmt.order_by(EventStore.occurred_at, EventStore.event_id)
        return self._session.scalars(stmt).all()

    def replay_by_event_type(
        self, event_type: str, *, tenant_id: Optional[uuid.UUID] = None
    ) -> Sequence[EventStore]:
        """All events of a given type (optionally tenant-scoped), time-ordered."""
        stmt = select(EventStore).where(EventStore.event_type == event_type)
        if tenant_id is not None:
            stmt = stmt.where(EventStore.tenant_id == tenant_id)
        stmt = stmt.order_by(EventStore.occurred_at, EventStore.event_id)
        return self._session.scalars(stmt).all()

    def replay_by_date(
        self, since: datetime, until: datetime, *, tenant_id: Optional[uuid.UUID] = None
    ) -> Sequence[EventStore]:
        """All events within ``[since, until)``, optionally tenant-scoped."""
        stmt = select(EventStore).where(
            EventStore.occurred_at >= since, EventStore.occurred_at < until
        )
        if tenant_id is not None:
            stmt = stmt.where(EventStore.tenant_id == tenant_id)
        stmt = stmt.order_by(EventStore.occurred_at, EventStore.event_id)
        return self._session.scalars(stmt).all()

    # ---- dead-letter replay (M2 brief: "replay capability") -----------
    def get_dead_letters(
        self,
        *,
        tenant_id: Optional[uuid.UUID] = None,
        consumer: Optional[str] = None,
        replayed: Optional[bool] = None,
        limit: int = 100,
    ) -> Sequence[DeadLetterEvent]:
        """List DLQ events for diagnosis; results are newest-failure-first.

        Parameters:
            tenant_id: Restrict to one tenant (``None`` = all visible tenants).
            consumer:  Restrict to one consumer name.
            replayed:  ``True`` → only already-replayed; ``False`` → only pending;
                       ``None`` → no filter.
            limit:     Maximum rows returned.
        """
        stmt = select(DeadLetterEvent).order_by(DeadLetterEvent.last_failed_at.desc()).limit(limit)
        if tenant_id is not None:
            stmt = stmt.where(DeadLetterEvent.tenant_id == tenant_id)
        if consumer is not None:
            stmt = stmt.where(DeadLetterEvent.consumer == consumer)
        if replayed is False:
            stmt = stmt.where(DeadLetterEvent.replayed_at.is_(None))
        elif replayed is True:
            stmt = stmt.where(DeadLetterEvent.replayed_at.is_not(None))
        return self._session.scalars(stmt).all()

    def mark_dead_letter_replayed(
        self,
        dlq_id: uuid.UUID,
        *,
        clear_processed: bool = True,
    ) -> Optional["EventEnvelope"]:
        """Prepare a DLQ entry for replay and return its original envelope.

        Stamps ``replayed_at`` on the DLQ row.  When ``clear_processed`` is
        ``True`` (default), also deletes the ``processed_events`` record so
        the consumer will re-process the event on the next publish.

        Returns the :class:`~app.events.envelope.EventEnvelope` reconstructed
        from the original ``event_store`` row so the caller can immediately
        re-publish it to the bus.  Returns ``None`` when the DLQ id is not
        found or the originating event_store row has been purged.

        The caller is responsible for re-publishing the returned envelope via
        the bus after this method returns (within the same unit of work or a
        fresh one).
        """
        from app.events.envelope import EventEnvelope  # avoid circular at module level

        dlq = self._session.get(DeadLetterEvent, dlq_id)
        if dlq is None:
            return None

        dlq.replayed_at = utcnow()

        if clear_processed:
            processed = self._session.get(
                ProcessedEvent, {"consumer": dlq.consumer, "event_id": dlq.event_id}
            )
            if processed is not None:
                self._session.delete(processed)

        event_record = self._session.get(EventStore, dlq.event_id)
        if event_record is None:
            logger.warning(
                "DLQ entry references event_id absent from event_store",
                dlq_id=str(dlq_id),
                event_id=str(dlq.event_id),
            )
            return None

        logger.info(
            "DLQ event marked for replay",
            dlq_id=str(dlq_id),
            event_id=str(dlq.event_id),
            event_type=dlq.event_type,
            consumer=dlq.consumer,
        )
        return EventEnvelope.from_record(event_record)


__all__ = ["EventStoreRepository"]
