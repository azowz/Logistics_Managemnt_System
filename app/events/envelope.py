"""The event envelope: a domain event plus its full transport/storage metadata.

The envelope is the unit that is persisted to ``event_store`` and published on the
:class:`~app.events.bus.EventBus`. It carries the canonical metadata required by
``docs/03`` §7 / the M2 brief:

    Event ID · Aggregate ID · Aggregate Version · Event Type · Event Version ·
    Tenant ID · Correlation ID · Causation ID · User ID · Timestamp · Metadata · Payload
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from app.common.datetime import utcnow
from app.db.uuidv7 import uuid7

if TYPE_CHECKING:  # pragma: no cover - typing only.
    from app.events.domain_event import DomainEvent


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """An immutable, fully-described event ready to persist and publish."""

    event_id: uuid.UUID
    tenant_id: uuid.UUID
    aggregate_type: str
    aggregate_id: uuid.UUID
    aggregate_version: int
    event_type: str
    event_version: int
    payload: dict[str, Any]
    occurred_at: datetime
    correlation_id: Optional[uuid.UUID] = None
    causation_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    metadata: Optional[dict[str, Any]] = field(default=None)

    @classmethod
    def create(
        cls,
        event: "DomainEvent",
        *,
        tenant_id: uuid.UUID,
        aggregate_id: uuid.UUID,
        aggregate_version: int,
        aggregate_type: Optional[str] = None,
        correlation_id: Optional[uuid.UUID] = None,
        causation_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
        occurred_at: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "EventEnvelope":
        """Wrap a :class:`DomainEvent` with a fresh id, timestamp, and metadata.

        ``aggregate_type`` defaults to the part of the event type before the verb
        is not reliably derivable, so it should normally be passed explicitly by
        the emitting aggregate/service.
        """
        return cls(
            event_id=uuid7(),
            tenant_id=tenant_id,
            aggregate_type=aggregate_type or "",
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_type=type(event).event_type,
            event_version=type(event).event_version,
            payload=event.to_payload(),
            occurred_at=occurred_at or utcnow(),
            correlation_id=correlation_id,
            causation_id=causation_id,
            user_id=user_id,
            metadata=metadata,
        )

    def to_record(self) -> dict[str, Any]:
        """Return kwargs for constructing an :class:`~app.models.event_store.EventStore` row.

        Note the ``event_metadata`` key: the ORM attribute is ``event_metadata``
        (mapped to the SQL column ``metadata``) because ``metadata`` is reserved
        by SQLAlchemy's declarative API.
        """
        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "payload": self.payload,
            "event_metadata": self.metadata,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "user_id": self.user_id,
            "occurred_at": self.occurred_at,
        }

    @classmethod
    def from_record(cls, record: Any) -> "EventEnvelope":
        """Build an envelope from a persisted ``EventStore`` row."""
        return cls(
            event_id=record.event_id,
            tenant_id=record.tenant_id,
            aggregate_type=record.aggregate_type,
            aggregate_id=record.aggregate_id,
            aggregate_version=record.aggregate_version,
            event_type=record.event_type,
            event_version=record.event_version,
            payload=dict(record.payload or {}),
            occurred_at=record.occurred_at,
            correlation_id=record.correlation_id,
            causation_id=record.causation_id,
            user_id=record.user_id,
            metadata=dict(record.event_metadata) if record.event_metadata else None,
        )


__all__ = ["EventEnvelope"]
