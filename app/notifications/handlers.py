"""Event-consumer wiring for the Notifications domain (context #19, Sprint 10).

A single :class:`NotificationEventHandler` subscribes to the operational events
that should produce notifications and turns each into an in-app notification via
:class:`~app.services.notification_service.NotificationService`. The handler runs
inside the event dispatcher's transaction (SAVEPOINT) and **never commits** — the
dispatcher commits the handler's writes together with the ``processed_events``
idempotency record, giving effectively-once delivery. A second, domain-level
idempotency guard (per-recipient idempotency key + unique constraint) prevents
duplicate rows even if the dispatcher guard is bypassed.

Recipient routing for Sprint 10 targets the event actor (see
``NotificationService.resolve_recipients``).
"""

from __future__ import annotations

from typing import ClassVar, Optional

from sqlalchemy.orm import Session

from app.events.bus import BaseEventHandler, EventBus, default_bus
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.models.enums import NotificationChannel, NotificationPriority
from app.observability.logging import get_logger
from app.services.notification_service import NotificationService

logger = get_logger(__name__)

# event_type → priority. The channel is in-app for every trigger in Sprint 10.
# Only events that exist in the registry are mapped (verified at build time).
_P = NotificationPriority
TRIGGER_PRIORITIES = {
    # Shipment lifecycle
    "ShipmentAssigned": _P.NORMAL,
    "ShipmentPickedUp": _P.NORMAL,
    "ShipmentInTransit": _P.NORMAL,
    "ShipmentDelayed": _P.HIGH,
    "ShipmentDelivered": _P.NORMAL,
    "ShipmentFailed": _P.HIGH,
    "ShipmentReturned": _P.HIGH,
    "ShipmentCancelled": _P.NORMAL,
    # Compliance & permits
    "DispatchBlockedByCompliance": _P.HIGH,
    "DispatchClearedByCompliance": _P.NORMAL,
    "PermitApproved": _P.NORMAL,
    "PermitRejected": _P.HIGH,
    "PermitExpired": _P.HIGH,
    # Insurance & claims
    "ClaimCreated": _P.NORMAL,
    "ClaimApproved": _P.NORMAL,
    "ClaimRejected": _P.HIGH,
    "ClaimSettled": _P.NORMAL,
    # Billing & settlements
    "InvoiceIssued": _P.NORMAL,
    "InvoicePaid": _P.NORMAL,
    "PaymentFailed": _P.HIGH,
    "SettlementApproved": _P.NORMAL,
    "SettlementSettled": _P.NORMAL,
}

TRIGGER_EVENT_TYPES = frozenset(TRIGGER_PRIORITIES)


class NotificationEventHandler(BaseEventHandler):
    """Creates in-app notifications from operational domain events."""

    name: ClassVar[str] = "notifications"
    event_types: ClassVar[Optional[frozenset]] = TRIGGER_EVENT_TYPES

    def __init__(self, *, provider_registry=None) -> None:
        self._provider_registry = provider_registry

    def handle(self, event: DomainEvent, envelope: EventEnvelope, session: Session) -> None:
        """Apply one event — idempotent, no commit (dispatcher owns the transaction)."""
        priority = TRIGGER_PRIORITIES.get(envelope.event_type, NotificationPriority.NORMAL)
        service = NotificationService(session, provider_registry=self._provider_registry)
        created = service.handle_domain_event(
            event,
            envelope,
            channel=NotificationChannel.IN_APP,
            priority=priority,
        )
        logger.debug(
            "Notification handler processed event",
            event_type=envelope.event_type,
            event_id=str(envelope.event_id),
            created=len(created),
        )


def register_notification_handlers(
    bus: Optional[EventBus] = None, *, provider_registry=None
) -> NotificationEventHandler:
    """Register the notification consumer on ``bus`` (defaults to the process bus).

    Idempotent: if a handler named ``notifications`` is already registered, the
    existing one is returned. Call this from the worker/relay bootstrap so the
    outbox relay fans operational events out to notifications.
    """
    bus = bus or default_bus
    for existing in getattr(bus, "handlers", ()):  # InProcessEventBus exposes .handlers
        if getattr(existing, "name", None) == NotificationEventHandler.name:
            return existing
    handler = NotificationEventHandler(provider_registry=provider_registry)
    bus.register(handler)
    return handler


__all__ = [
    "NotificationEventHandler",
    "register_notification_handlers",
    "TRIGGER_EVENT_TYPES",
    "TRIGGER_PRIORITIES",
]
