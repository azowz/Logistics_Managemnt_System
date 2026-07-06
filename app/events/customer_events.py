"""Customer domain events (Sprint 3).

All events are frozen dataclasses that extend :class:`~app.events.domain_event.DomainEvent`
and are registered on the process-wide :data:`~app.events.registry.event_registry` via
:func:`~app.events.registry.register_event`.

Naming convention: ``<Aggregate><PastTenseVerb>`` (ADR-007 / docs/03 §7).
Each event carries only the *business payload* — envelope metadata (tenant, actor,
timestamps, correlation) is added by :class:`~app.events.envelope.EventEnvelope`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.events.domain_event import DomainEvent
from app.events.registry import register_event


@register_event
@dataclass(frozen=True, slots=True)
class CustomerCreated(DomainEvent):
    """A new customer record was persisted for the first time."""

    event_type = "CustomerCreated"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    company_name: str
    customer_type: str
    status: str


@register_event
@dataclass(frozen=True, slots=True)
class CustomerUpdated(DomainEvent):
    """Mutable customer fields were modified."""

    event_type = "CustomerUpdated"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    # JSON-safe dict of the fields that changed: {"field": new_value}
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class CustomerActivated(DomainEvent):
    """Customer status changed from suspended/inactive → active."""

    event_type = "CustomerActivated"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class CustomerSuspended(DomainEvent):
    """Customer status changed → suspended."""

    event_type = "CustomerSuspended"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class CustomerDeleted(DomainEvent):
    """Customer was soft-deleted (logical removal only)."""

    event_type = "CustomerDeleted"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    deleted_by: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class CustomerRestored(DomainEvent):
    """A previously soft-deleted customer was restored."""

    event_type = "CustomerRestored"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class CustomerContactUpdated(DomainEvent):
    """Customer contact details (phone / email / contact person) changed."""

    event_type = "CustomerContactUpdated"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class CustomerAddressUpdated(DomainEvent):
    """Customer address or geo-coordinates changed."""

    event_type = "CustomerAddressUpdated"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class CustomerStatusChanged(DomainEvent):
    """General status transition event (captures any status change)."""

    event_type = "CustomerStatusChanged"
    event_version = 1

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    new_status: str
    reason: Optional[str]


__all__ = [
    "CustomerCreated",
    "CustomerUpdated",
    "CustomerActivated",
    "CustomerSuspended",
    "CustomerDeleted",
    "CustomerRestored",
    "CustomerContactUpdated",
    "CustomerAddressUpdated",
    "CustomerStatusChanged",
]
