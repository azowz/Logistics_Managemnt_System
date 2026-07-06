"""Notifications & Communications domain events (context #19, Sprint 10).

Frozen, slotted dataclasses registered on the process-wide registry. Naming
``<Aggregate><PastTenseVerb>`` (ADR-007). Business payload only; envelope
metadata is added by :class:`~app.events.envelope.EventEnvelope`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from app.events.domain_event import DomainEvent
from app.events.registry import register_event


# --- Template --------------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class NotificationTemplateCreated(DomainEvent):
    event_type = "NotificationTemplateCreated"
    event_version = 1
    template_id: uuid.UUID
    tenant_id: uuid.UUID
    template_code: str
    channel: str


@register_event
@dataclass(frozen=True, slots=True)
class NotificationTemplateUpdated(DomainEvent):
    event_type = "NotificationTemplateUpdated"
    event_version = 1
    template_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class NotificationTemplateActivated(DomainEvent):
    event_type = "NotificationTemplateActivated"
    event_version = 1
    template_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class NotificationTemplateDeactivated(DomainEvent):
    event_type = "NotificationTemplateDeactivated"
    event_version = 1
    template_id: uuid.UUID
    tenant_id: uuid.UUID


# --- Notification lifecycle ------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class NotificationCreated(DomainEvent):
    event_type = "NotificationCreated"
    event_version = 1
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    channel: str
    status: str
    source_event_type: Optional[str]
    recipient_user_id: Optional[uuid.UUID]
    # Sprint 12 enrichment (additive, v1-compatible): older payloads omit this and
    # deserialize with priority=None.
    priority: Optional[str] = None


@register_event
@dataclass(frozen=True, slots=True)
class NotificationQueued(DomainEvent):
    event_type = "NotificationQueued"
    event_version = 1
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class NotificationSent(DomainEvent):
    event_type = "NotificationSent"
    event_version = 1
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    channel: str
    provider: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class NotificationFailed(DomainEvent):
    event_type = "NotificationFailed"
    event_version = 1
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    channel: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class NotificationRetried(DomainEvent):
    event_type = "NotificationRetried"
    event_version = 1
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    retry_count: int


@register_event
@dataclass(frozen=True, slots=True)
class NotificationCancelled(DomainEvent):
    event_type = "NotificationCancelled"
    event_version = 1
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class NotificationRead(DomainEvent):
    event_type = "NotificationRead"
    event_version = 1
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    recipient_user_id: Optional[uuid.UUID]
    priority: Optional[str] = None  # Sprint 12 enrichment (additive, v1-compatible)


@register_event
@dataclass(frozen=True, slots=True)
class NotificationDeliveryAttemptCreated(DomainEvent):
    event_type = "NotificationDeliveryAttemptCreated"
    event_version = 1
    attempt_id: uuid.UUID
    tenant_id: uuid.UUID
    notification_id: uuid.UUID
    channel: str
    status: str
    attempt_number: int


__all__ = [
    "NotificationTemplateCreated",
    "NotificationTemplateUpdated",
    "NotificationTemplateActivated",
    "NotificationTemplateDeactivated",
    "NotificationCreated",
    "NotificationQueued",
    "NotificationSent",
    "NotificationFailed",
    "NotificationRetried",
    "NotificationCancelled",
    "NotificationRead",
    "NotificationDeliveryAttemptCreated",
]
