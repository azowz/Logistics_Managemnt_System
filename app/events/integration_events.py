"""External Integrations & Webhooks domain events (context #21, Sprint 13).

Frozen, slotted dataclasses registered on the process-wide registry. Naming
``<Aggregate><PastTenseVerb>`` (ADR-007). Business payload only; envelope metadata is
added by :class:`~app.events.envelope.EventEnvelope`. Secrets are NEVER placed in an
event payload — only ids, prefixes, statuses, and non-sensitive descriptors.

These are *internal* platform events (they drive audit/analytics). They are distinct
from the *external* webhook event names partners subscribe to (see
``app.integrations.event_mapping``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from app.events.domain_event import DomainEvent
from app.events.registry import register_event


# --- Integration partner ----------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class IntegrationPartnerCreated(DomainEvent):
    event_type = "IntegrationPartnerCreated"
    event_version = 1
    partner_id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    partner_type: str
    status: str


@register_event
@dataclass(frozen=True, slots=True)
class IntegrationPartnerUpdated(DomainEvent):
    event_type = "IntegrationPartnerUpdated"
    event_version = 1
    partner_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class IntegrationPartnerSuspended(DomainEvent):
    event_type = "IntegrationPartnerSuspended"
    event_version = 1
    partner_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class IntegrationPartnerActivated(DomainEvent):
    event_type = "IntegrationPartnerActivated"
    event_version = 1
    partner_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


# --- Partner API key --------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class PartnerApiKeyCreated(DomainEvent):
    event_type = "PartnerApiKeyCreated"
    event_version = 1
    api_key_id: uuid.UUID
    tenant_id: uuid.UUID
    partner_id: uuid.UUID
    key_prefix: str


@register_event
@dataclass(frozen=True, slots=True)
class PartnerApiKeyRevoked(DomainEvent):
    event_type = "PartnerApiKeyRevoked"
    event_version = 1
    api_key_id: uuid.UUID
    tenant_id: uuid.UUID
    partner_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class PartnerApiKeyRotated(DomainEvent):
    event_type = "PartnerApiKeyRotated"
    event_version = 1
    api_key_id: uuid.UUID
    tenant_id: uuid.UUID
    partner_id: uuid.UUID
    new_key_prefix: str


# --- Webhook subscription ---------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class WebhookSubscriptionCreated(DomainEvent):
    event_type = "WebhookSubscriptionCreated"
    event_version = 1
    subscription_id: uuid.UUID
    tenant_id: uuid.UUID
    partner_id: uuid.UUID
    status: str


@register_event
@dataclass(frozen=True, slots=True)
class WebhookSubscriptionUpdated(DomainEvent):
    event_type = "WebhookSubscriptionUpdated"
    event_version = 1
    subscription_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class WebhookSubscriptionActivated(DomainEvent):
    event_type = "WebhookSubscriptionActivated"
    event_version = 1
    subscription_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class WebhookSubscriptionDeactivated(DomainEvent):
    event_type = "WebhookSubscriptionDeactivated"
    event_version = 1
    subscription_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


# --- Webhook delivery -------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class WebhookDeliveryCreated(DomainEvent):
    event_type = "WebhookDeliveryCreated"
    event_version = 1
    delivery_id: uuid.UUID
    tenant_id: uuid.UUID
    subscription_id: uuid.UUID
    source_event_id: uuid.UUID
    external_event_type: str


@register_event
@dataclass(frozen=True, slots=True)
class WebhookDeliveryAttempted(DomainEvent):
    event_type = "WebhookDeliveryAttempted"
    event_version = 1
    delivery_id: uuid.UUID
    tenant_id: uuid.UUID
    attempt_number: int
    status: str


@register_event
@dataclass(frozen=True, slots=True)
class WebhookDeliverySucceeded(DomainEvent):
    event_type = "WebhookDeliverySucceeded"
    event_version = 1
    delivery_id: uuid.UUID
    tenant_id: uuid.UUID
    subscription_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class WebhookDeliveryFailed(DomainEvent):
    event_type = "WebhookDeliveryFailed"
    event_version = 1
    delivery_id: uuid.UUID
    tenant_id: uuid.UUID
    subscription_id: uuid.UUID
    reason: Optional[str]


# --- Inbound integration events ---------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class InboundIntegrationEventReceived(DomainEvent):
    event_type = "InboundIntegrationEventReceived"
    event_version = 1
    inbound_event_id: uuid.UUID
    tenant_id: uuid.UUID
    partner_id: uuid.UUID
    api_key_id: uuid.UUID
    inbound_type: str


@register_event
@dataclass(frozen=True, slots=True)
class InboundIntegrationEventAccepted(DomainEvent):
    event_type = "InboundIntegrationEventAccepted"
    event_version = 1
    inbound_event_id: uuid.UUID
    tenant_id: uuid.UUID
    partner_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class InboundIntegrationEventRejected(DomainEvent):
    event_type = "InboundIntegrationEventRejected"
    event_version = 1
    inbound_event_id: uuid.UUID
    tenant_id: uuid.UUID
    partner_id: uuid.UUID
    reason: Optional[str]


__all__ = [
    "IntegrationPartnerCreated",
    "IntegrationPartnerUpdated",
    "IntegrationPartnerSuspended",
    "IntegrationPartnerActivated",
    "PartnerApiKeyCreated",
    "PartnerApiKeyRevoked",
    "PartnerApiKeyRotated",
    "WebhookSubscriptionCreated",
    "WebhookSubscriptionUpdated",
    "WebhookSubscriptionActivated",
    "WebhookSubscriptionDeactivated",
    "WebhookDeliveryCreated",
    "WebhookDeliveryAttempted",
    "WebhookDeliverySucceeded",
    "WebhookDeliveryFailed",
    "InboundIntegrationEventReceived",
    "InboundIntegrationEventAccepted",
    "InboundIntegrationEventRejected",
]
