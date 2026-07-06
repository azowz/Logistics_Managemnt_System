"""Webhook fan-out consumer (context #21, Sprint 13).

A :class:`BaseEventHandler` that turns mapped internal domain events into sanitized,
signed ``webhook_deliveries`` for matching active subscriptions. Runs inside the
dispatcher SAVEPOINT (idempotency key ``"webhooks"``) and **never commits** — the
dispatcher owns the transaction. Registration is idempotent and wired into the outbox
relay alongside the notifications and analytics consumers.
"""

from __future__ import annotations

from typing import ClassVar, Optional

from sqlalchemy.orm import Session

from app.events.bus import BaseEventHandler, EventBus, default_bus
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.integrations.event_mapping import SUPPORTED_INTERNAL_EVENT_TYPES
from app.observability.logging import get_logger
from app.services.integration_service import IntegrationService

logger = get_logger(__name__)


class WebhookEventHandler(BaseEventHandler):
    """Creates outbound webhook deliveries from publishable domain events."""

    name: ClassVar[str] = "webhooks"
    event_types: ClassVar[Optional[frozenset]] = SUPPORTED_INTERNAL_EVENT_TYPES

    def handle(self, event: DomainEvent, envelope: EventEnvelope, session: Session) -> None:
        """Fan the event out to matching subscriptions. Idempotent, no commit."""
        created = IntegrationService(session).create_deliveries_from_event(envelope)
        logger.debug(
            "Webhook handler processed event",
            event_type=envelope.event_type,
            event_id=str(envelope.event_id),
            deliveries=len(created),
        )


def register_webhook_handlers(bus: Optional[EventBus] = None) -> WebhookEventHandler:
    """Register the webhook consumer on ``bus`` (defaults to the process bus). Idempotent."""
    bus = bus or default_bus
    for existing in getattr(bus, "handlers", ()):
        if getattr(existing, "name", None) == WebhookEventHandler.name:
            return existing
    handler = WebhookEventHandler()
    bus.register(handler)
    return handler


__all__ = ["WebhookEventHandler", "register_webhook_handlers"]
