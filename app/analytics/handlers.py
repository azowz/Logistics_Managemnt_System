"""Event-consumer wiring for Reporting & Analytics projections (Sprint 11).

A single :class:`AnalyticsProjectionHandler` subscribes to the operational events
that feed the read-side projections and applies each via
:class:`~app.services.projection_service.ProjectionService`. The handler runs
inside the event dispatcher's transaction (SAVEPOINT) and **never commits** — the
dispatcher commits the projection writes together with the ``processed_events``
idempotency record, giving effectively-once application. Projection handlers never
mutate source aggregates and never emit source-domain events.
"""

from __future__ import annotations

from typing import ClassVar, Optional

from sqlalchemy.orm import Session

from app.events.bus import BaseEventHandler, EventBus, default_bus
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.observability.logging import get_logger
from app.services.projection_service import ALL_EVENT_TYPES, ProjectionService

logger = get_logger(__name__)


class AnalyticsProjectionHandler(BaseEventHandler):
    """Applies operational events to read-side projection tables."""

    name: ClassVar[str] = "analytics"
    event_types: ClassVar[Optional[frozenset]] = ALL_EVENT_TYPES

    def handle(self, event: DomainEvent, envelope: EventEnvelope, session: Session) -> None:
        applied = ProjectionService(session).handle_domain_event(envelope)
        logger.debug(
            "Analytics projection applied event",
            event_type=envelope.event_type,
            event_id=str(envelope.event_id),
            applied=applied,
        )


def register_analytics_handlers(bus: Optional[EventBus] = None) -> AnalyticsProjectionHandler:
    """Register the analytics projection consumer on ``bus`` (defaults to the process bus).

    Idempotent: if a handler named ``analytics`` is already registered, the
    existing one is returned. Called by ``run_outbox_relay`` against the bus it
    publishes through, so projections stay current wherever the relay runs.
    """
    bus = bus or default_bus
    for existing in getattr(bus, "handlers", ()):
        if getattr(existing, "name", None) == AnalyticsProjectionHandler.name:
            return existing
    handler = AnalyticsProjectionHandler()
    bus.register(handler)
    return handler


__all__ = ["AnalyticsProjectionHandler", "register_analytics_handlers"]
