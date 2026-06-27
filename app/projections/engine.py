"""Projection base + rebuild engine (M2).

A :class:`Projection` is an event handler that maintains a denormalized read model
and can **reset** that model so it can be rebuilt by replaying the event log
(ADR-006: "rebuildable from the append-only log"). The :class:`ProjectionRebuilder`
truncates a projection's state and re-folds events, ordered, under the correct
tenant scope — the operational recovery path for projection drift or a new
read model.
"""

from __future__ import annotations

import abc
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.events import metrics
from app.events.bus import BaseEventHandler
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.events.registry import EventRegistry, event_registry
from app.observability.logging import get_logger
from app.repositories.event_store_repository import EventStoreRepository

logger = get_logger(__name__)


class Projection(BaseEventHandler, abc.ABC):
    """A read-model builder: applies events and can reset its model for rebuild."""

    @abc.abstractmethod
    def handle(self, event: DomainEvent, envelope: EventEnvelope, session: Session) -> None:
        """Apply one event to the read model (idempotent upsert recommended)."""
        raise NotImplementedError

    @abc.abstractmethod
    def reset(self, session: Session, tenant_id: Optional[uuid.UUID] = None) -> None:
        """Clear the read model (optionally scoped to one tenant) prior to rebuild."""
        raise NotImplementedError


class ProjectionRebuilder:
    """Rebuilds a projection by replaying the event log (ADR-006)."""

    def __init__(self, *, registry: EventRegistry | None = None) -> None:
        self._registry = registry or event_registry

    def rebuild_by_tenant(self, projection: Projection, tenant_id: uuid.UUID) -> int:
        """Reset + re-fold all of a tenant's events into ``projection``.

        Runs in a single tenant-scoped transaction so reads/writes are RLS-correct
        and the rebuild is atomic (all-or-nothing). Returns the number of events
        applied.
        """
        applied = 0
        with metrics.REPLAY_DURATION.labels("tenant").time():
            with session_scope(tenant_id) as session:
                repo = EventStoreRepository(session)
                projection.reset(session, tenant_id)
                for row in repo.replay_by_tenant(tenant_id):
                    envelope = EventEnvelope.from_record(row)
                    if not projection.handles(envelope.event_type):
                        continue
                    event = self._registry.deserialize(envelope)
                    with session.begin_nested():
                        projection.handle(event, envelope, session)
                    applied += 1
        logger.info(
            "Projection rebuilt for tenant",
            projection=projection.name, tenant_id=str(tenant_id), events_applied=applied,
        )
        return applied

    def rebuild_by_aggregate(
        self, projection: Projection, tenant_id: uuid.UUID, aggregate_type: str, aggregate_id: uuid.UUID
    ) -> int:
        """Re-fold a single aggregate's stream into ``projection`` (no global reset)."""
        applied = 0
        with metrics.REPLAY_DURATION.labels("aggregate").time():
            with session_scope(tenant_id) as session:
                repo = EventStoreRepository(session)
                for row in repo.replay_by_aggregate(aggregate_type, aggregate_id):
                    envelope = EventEnvelope.from_record(row)
                    if not projection.handles(envelope.event_type):
                        continue
                    event = self._registry.deserialize(envelope)
                    with session.begin_nested():
                        projection.handle(event, envelope, session)
                    applied += 1
        logger.info(
            "Projection rebuilt for aggregate",
            projection=projection.name, aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id), events_applied=applied,
        )
        return applied


__all__ = ["Projection", "ProjectionRebuilder"]
