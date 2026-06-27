"""Event-backbone persistence models (M2): event store, outbox, idempotency, DLQ.

These tables are the durable foundation of the platform's CQRS-lite + Event-Driven
Architecture (ADR-004 / ADR-007, ``docs/03`` §7, ``docs/11`` §6):

* :class:`EventStore`      — the single, append-only, immutable domain-event log
  **and** the transactional outbox (one local transaction writes the aggregate
  change *and* the event; a relay later publishes rows where ``published_at IS
  NULL``). Per-aggregate ordering / optimistic concurrency is enforced by
  ``UNIQUE(aggregate_id, aggregate_version)``.
* :class:`ProcessedEvent`  — per-consumer idempotency ledger (at-least-once →
  effectively-once); consumers dedupe on ``event_id``.
* :class:`DeadLetterEvent` — events whose delivery exhausted retries; retains
  enough context to diagnose and replay.
* :class:`OutboxRelayState`— relay cursor/heartbeat for lag monitoring.

**Partitioning note (reconciliation, ``docs/10`` review).** PostgreSQL requires a
unique constraint on a partitioned table to include every partition-key column.
That is incompatible with a *global* ``UNIQUE(aggregate_id, aggregate_version)``
when partitioning by ``occurred_at``. Because that per-aggregate-version
uniqueness is the concurrency guarantee, ``event_store`` is intentionally
**non-partitioned**; it stays partition-ready (UUIDv7 PK, time index, BRIN-able)
and native time-partitioning is a deferred, ADR-gated scale decision.

**Immutability.** Append-only is enforced operationally by granting the
application role ``INSERT``/``SELECT`` only (no ``UPDATE``/``DELETE``) on
``event_store``; that grant requires the dedicated non-superuser role tracked as
``docs/10`` R-1 and is applied with the role migration, not here. The outbox
mutation of ``published_at``/retry columns is performed by the relay under a
separate maintenance grant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.uuidv7 import uuid7


class EventStore(Base):
    """Append-only canonical domain-event log + transactional outbox."""

    __tablename__ = "event_store"
    __table_args__ = (
        # Per-aggregate ordering + optimistic concurrency: two writers racing to
        # the same next version collide here; the loser retries and re-validates.
        UniqueConstraint(
            "aggregate_id",
            "aggregate_version",
            name="uq_event_store_aggregate_id_aggregate_version",
        ),
        # Outbox poll: only unpublished rows (cheap partial index).
        Index(
            "ix_event_store_unpublished",
            "next_attempt_at",
            postgresql_where=text("published_at IS NULL"),
        ),
        # Replay by tenant / date window.
        Index("ix_event_store_tenant_id_occurred_at", "tenant_id", "occurred_at"),
        # Replay by aggregate (ordered).
        Index(
            "ix_event_store_aggregate",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
        ),
        # Replay by event type within a tenant.
        Index("ix_event_store_tenant_id_event_type", "tenant_id", "event_type"),
    )

    # ``event_id`` is the PK AND the cross-system idempotency key (UUIDv7 →
    # time-ordered for index locality on this append-heavy table).
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # ``metadata`` is reserved by SQLAlchemy's declarative API, so the Python
    # attribute is ``event_metadata`` while the column stays ``metadata``.
    event_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    causation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    # Business time the fact occurred vs. the ingest time it was recorded.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # ---- Transactional-outbox columns ----------------------------------
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text())
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only.
        return (
            f"<EventStore event_id={self.event_id!s} type={self.event_type} "
            f"agg={self.aggregate_type}:{self.aggregate_id!s} v{self.aggregate_version}>"
        )


class ProcessedEvent(Base):
    """Per-consumer idempotency ledger: ``(consumer, event_id)`` already handled."""

    __tablename__ = "processed_events"

    consumer: Mapped[str] = mapped_column(String(150), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeadLetterEvent(Base):
    """An event whose delivery to a consumer exhausted its retry budget.

    Retains the failing consumer, a payload snapshot, the failure reason, and the
    retry count so an operator (or an automated job) can diagnose and replay.
    """

    __tablename__ = "dead_letter_events"
    __table_args__ = (
        Index("ix_dead_letter_events_tenant_id_last_failed_at", "tenant_id", "last_failed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    consumer: Mapped[str] = mapped_column(String(150), nullable=False)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text(), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    replayed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxRelayState(Base):
    """Relay cursor / heartbeat for outbox-lag observability (infra, not tenant data)."""

    __tablename__ = "outbox_relay_state"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    relay_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    last_published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    published_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = ["EventStore", "ProcessedEvent", "DeadLetterEvent", "OutboxRelayState"]
