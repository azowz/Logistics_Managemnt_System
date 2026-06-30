"""Shipment domain events (Sprint 5).

Frozen, slotted dataclasses registered on the process-wide event registry and
written to the transactional outbox in the same transaction as the aggregate
(mirrors ``customer_events`` / ``order_events``). ``tenant_id`` is duplicated in
the payload to stay consistent with those precedents (also on the envelope).
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
    """A new shipment was persisted (status=created)."""

    event_type = "ShipmentCreated"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    reference_code: str
    client_id: uuid.UUID
    order_id: Optional[uuid.UUID]
    origin_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
    status: str
    priority: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentMarkedReady(DomainEvent):
    """Shipment was published as ready for assignment (created → ready)."""

    event_type = "ShipmentMarkedReady"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentAssigned(DomainEvent):
    """Driver (and optionally vehicle) assigned (ready → assigned)."""

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
    """Cargo collected (assigned → picked_up)."""

    event_type = "ShipmentPickedUp"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    picked_up_at: Optional[str]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentInTransit(DomainEvent):
    """Shipment moving toward destination (picked_up/delayed → in_transit)."""

    event_type = "ShipmentInTransit"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDelayed(DomainEvent):
    """Shipment flagged delayed (overlay over the active lifecycle)."""

    event_type = "ShipmentDelayed"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDelivered(DomainEvent):
    """Shipment delivered (terminal)."""

    event_type = "ShipmentDelivered"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    delivered_at: Optional[str]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentFailed(DomainEvent):
    """Delivery attempt failed (may be followed by a return)."""

    event_type = "ShipmentFailed"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentReturned(DomainEvent):
    """Shipment returned to origin (terminal)."""

    event_type = "ShipmentReturned"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentCancelled(DomainEvent):
    """Shipment cancelled (terminal). ``compensation_required`` is True when
    cancelling after resources were committed (assigned/picked_up/in_transit/delayed)."""

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
    """Mutable shipment fields changed."""

    event_type = "ShipmentUpdated"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDeleted(DomainEvent):
    """Shipment soft-deleted."""

    event_type = "ShipmentDeleted"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    deleted_by: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentRestored(DomainEvent):
    """Soft-deleted shipment restored."""

    event_type = "ShipmentRestored"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentAddressChanged(DomainEvent):
    """Origin/destination warehouse routing changed."""

    event_type = "ShipmentAddressChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentCargoChanged(DomainEvent):
    """Cargo attributes (weight/volume/type/description) changed."""

    event_type = "ShipmentCargoChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDriverChanged(DomainEvent):
    """Assigned driver changed (assignment or reassignment)."""

    event_type = "ShipmentDriverChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_driver_id: Optional[uuid.UUID]
    new_driver_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentVehicleChanged(DomainEvent):
    """Assigned vehicle changed (assignment or reassignment)."""

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
