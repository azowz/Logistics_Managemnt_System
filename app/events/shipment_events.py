"""Shipment domain events (Sprint 5).

All events are frozen, slotted dataclasses that extend
:class:`~app.events.domain_event.DomainEvent` and are registered on the
process-wide :data:`~app.events.registry.event_registry` via
:func:`~app.events.registry.register_event`.

Naming convention: ``Shipment<PastTenseVerb>`` (ADR-007 / docs/04). Each event
carries only the *business payload* — envelope metadata (actor, timestamps,
correlation, aggregate version) is added by
:class:`~app.events.envelope.EventEnvelope`.

NOTE: ``tenant_id`` is intentionally duplicated in the payload to stay
consistent with the Sprint 3/4 ``customer_events`` / ``order_events`` precedent
(it is also present on the envelope). This is tracked as a cross-cutting
reconciliation item.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.events.domain_event import DomainEvent
from app.events.registry import register_event


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentCreated(DomainEvent):
    """A new shipment was persisted for the first time (status=created)."""

    event_type = "ShipmentCreated"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    reference_code: str
    client_id: uuid.UUID
    origin_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
    order_id: Optional[uuid.UUID]
    status: str
    priority: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentMarkedReady(DomainEvent):
    """Shipment was marked ready for assignment (created → ready)."""

    event_type = "ShipmentMarkedReady"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentAssigned(DomainEvent):
    """Shipment was assigned to a driver (and optionally a vehicle)."""

    event_type = "ShipmentAssigned"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    driver_id: Optional[uuid.UUID]
    vehicle_id: Optional[uuid.UUID]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentPickedUp(DomainEvent):
    """Cargo was picked up by the assigned driver (assigned → picked_up)."""

    event_type = "ShipmentPickedUp"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    picked_up_at: Optional[str]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentInTransit(DomainEvent):
    """Shipment entered transit toward the destination (picked_up → in_transit)."""

    event_type = "ShipmentInTransit"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDelayed(DomainEvent):
    """Shipment was flagged as delayed (in-transit overlay)."""

    event_type = "ShipmentDelayed"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDelivered(DomainEvent):
    """Shipment reached its destination (in_transit/delayed → delivered, terminal)."""

    event_type = "ShipmentDelivered"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    delivered_at: Optional[str]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentFailed(DomainEvent):
    """Shipment delivery failed (in-progress → failed)."""

    event_type = "ShipmentFailed"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentReturned(DomainEvent):
    """Shipment was returned to origin (in-progress/failed → returned, terminal)."""

    event_type = "ShipmentReturned"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentCancelled(DomainEvent):
    """Shipment was cancelled (any pre-delivery → cancelled, terminal).

    ``compensation_required`` is True when cancelling from a committed state
    (assigned / picked_up / in_transit / delayed), signalling downstream
    compensation workflows.
    """

    event_type = "ShipmentCancelled"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]
    compensation_required: bool


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentUpdated(DomainEvent):
    """Mutable shipment fields were modified."""

    event_type = "ShipmentUpdated"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDeleted(DomainEvent):
    """Shipment was soft-deleted (logical removal only)."""

    event_type = "ShipmentDeleted"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    deleted_by: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentRestored(DomainEvent):
    """A previously soft-deleted shipment was restored."""

    event_type = "ShipmentRestored"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentAddressChanged(DomainEvent):
    """Origin/destination warehouse changed."""

    event_type = "ShipmentAddressChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentCargoChanged(DomainEvent):
    """Cargo metadata (type / description / weight / volume) changed."""

    event_type = "ShipmentCargoChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDriverChanged(DomainEvent):
    """Assigned driver changed (reassignment)."""

    event_type = "ShipmentDriverChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_driver_id: Optional[uuid.UUID]
    new_driver_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentVehicleChanged(DomainEvent):
    """Assigned vehicle changed (reassignment)."""

    event_type = "ShipmentVehicleChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_vehicle_id: Optional[uuid.UUID]
    new_vehicle_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentStatusChanged(DomainEvent):
    """General status-transition event (captures every status change)."""

    event_type = "ShipmentStatusChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    new_status: str
    reason: Optional[str]


__all__ = [
    "ShipmentCreated",
    "ShipmentMarkedReady",
    "ShipmentAssigned",
    "ShipmentPickedUp",
    "ShipmentInTransit",
    "ShipmentDelayed",
    "ShipmentDelivered",
    "ShipmentFailed",
    "ShipmentReturned",
    "ShipmentCancelled",
    "ShipmentUpdated",
    "ShipmentDeleted",
    "ShipmentRestored",
    "ShipmentAddressChanged",
    "ShipmentCargoChanged",
    "ShipmentDriverChanged",
    "ShipmentVehicleChanged",
    "ShipmentStatusChanged",
]
