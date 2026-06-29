"""Order domain events (Sprint 4).

All events are frozen dataclasses that extend
:class:`~app.events.domain_event.DomainEvent` and are registered on the
process-wide :data:`~app.events.registry.event_registry` via
:func:`~app.events.registry.register_event`.

Naming convention: ``<Aggregate><PastTenseVerb>`` (ADR-007 / docs/04).
Each event carries only the *business payload* — envelope metadata (actor,
timestamps, correlation, aggregate version) is added by
:class:`~app.events.envelope.EventEnvelope`.

NOTE: ``tenant_id`` is intentionally duplicated in the payload to stay
consistent with the Sprint 3 ``customer_events`` precedent (it is also present
on the envelope). This is tracked as a cross-cutting reconciliation item.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.events.domain_event import DomainEvent
from app.events.registry import register_event


@register_event
@dataclass(frozen=True, slots=True)
class OrderCreated(DomainEvent):
    """A new order was persisted for the first time (status=draft)."""

    event_type = "OrderCreated"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    order_number: str
    order_type: str
    order_source: str
    priority: str
    status: str


@register_event
@dataclass(frozen=True, slots=True)
class OrderSubmitted(DomainEvent):
    """Order was submitted for approval (draft → submitted)."""

    event_type = "OrderSubmitted"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class OrderApproved(DomainEvent):
    """Order was approved (submitted → approved)."""

    event_type = "OrderApproved"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class OrderScheduled(DomainEvent):
    """Order was scheduled for pickup/delivery (approved → scheduled)."""

    event_type = "OrderScheduled"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class OrderAssigned(DomainEvent):
    """Order was assigned to a dispatcher (scheduled → assigned)."""

    event_type = "OrderAssigned"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    assigned_dispatcher_id: Optional[uuid.UUID]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class OrderPickedUp(DomainEvent):
    """Cargo was picked up; transit begins (assigned → in_transit)."""

    event_type = "OrderPickedUp"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    picked_up_at: Optional[str]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class OrderInTransit(DomainEvent):
    """Order is in transit toward the delivery location."""

    event_type = "OrderInTransit"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class OrderDelivered(DomainEvent):
    """Order reached its delivery location (in_transit → delivered, terminal)."""

    event_type = "OrderDelivered"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    delivered_at: Optional[str]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class OrderCancelled(DomainEvent):
    """Order was cancelled (any non-terminal → cancelled, terminal).

    ``compensation_required`` is True when cancelling from an in-progress state
    (assigned / in_transit), signalling downstream compensation workflows.
    """

    event_type = "OrderCancelled"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]
    compensation_required: bool


@register_event
@dataclass(frozen=True, slots=True)
class OrderFailed(DomainEvent):
    """Order failed and cannot be fulfilled (non-terminal → failed, terminal)."""

    event_type = "OrderFailed"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class OrderRestored(DomainEvent):
    """A previously soft-deleted order was restored."""

    event_type = "OrderRestored"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class OrderUpdated(DomainEvent):
    """Mutable order fields were modified."""

    event_type = "OrderUpdated"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class OrderPriorityChanged(DomainEvent):
    """Order priority was changed."""

    event_type = "OrderPriorityChanged"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_priority: str
    new_priority: str


@register_event
@dataclass(frozen=True, slots=True)
class OrderAddressChanged(DomainEvent):
    """Order pickup/delivery location or coordinates changed."""

    event_type = "OrderAddressChanged"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class OrderStatusChanged(DomainEvent):
    """General status-transition event (captures every status change)."""

    event_type = "OrderStatusChanged"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    new_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class OrderDeleted(DomainEvent):
    """Order was soft-deleted (logical removal only)."""

    event_type = "OrderDeleted"
    event_version = 1

    order_id: uuid.UUID
    tenant_id: uuid.UUID
    deleted_by: Optional[uuid.UUID]


__all__ = [
    "OrderCreated",
    "OrderSubmitted",
    "OrderApproved",
    "OrderScheduled",
    "OrderAssigned",
    "OrderPickedUp",
    "OrderInTransit",
    "OrderDelivered",
    "OrderCancelled",
    "OrderFailed",
    "OrderRestored",
    "OrderUpdated",
    "OrderPriorityChanged",
    "OrderAddressChanged",
    "OrderStatusChanged",
    "OrderDeleted",
]
