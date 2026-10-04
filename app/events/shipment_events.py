"""Shipment domain events (Sprint 5).

<<<<<<< HEAD
Frozen, slotted dataclasses registered on the process-wide event registry and
written to the transactional outbox in the same transaction as the aggregate
(mirrors ``customer_events`` / ``order_events``). ``tenant_id`` is duplicated in
the payload to stay consistent with those precedents (also on the envelope).
=======
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
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49
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
<<<<<<< HEAD
    """A new shipment was persisted (status=created)."""
=======
    """A new shipment was persisted for the first time (status=created)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentCreated"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    reference_code: str
    client_id: uuid.UUID
<<<<<<< HEAD
    order_id: Optional[uuid.UUID]
    origin_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
=======
    origin_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
    order_id: Optional[uuid.UUID]
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49
    status: str
    priority: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentMarkedReady(DomainEvent):
<<<<<<< HEAD
    """Shipment was published as ready for assignment (created → ready)."""
=======
    """Shipment was marked ready for assignment (created → ready)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentMarkedReady"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentAssigned(DomainEvent):
<<<<<<< HEAD
    """Driver (and optionally vehicle) assigned (ready → assigned)."""
=======
    """Shipment was assigned to a driver (and optionally a vehicle)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

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
<<<<<<< HEAD
    """Cargo collected (assigned → picked_up)."""
=======
    """Cargo was picked up by the assigned driver (assigned → picked_up)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentPickedUp"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    picked_up_at: Optional[str]
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentInTransit(DomainEvent):
<<<<<<< HEAD
    """Shipment moving toward destination (picked_up/delayed → in_transit)."""
=======
    """Shipment entered transit toward the destination (picked_up → in_transit)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentInTransit"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDelayed(DomainEvent):
<<<<<<< HEAD
    """Shipment flagged delayed (overlay over the active lifecycle)."""
=======
    """Shipment was flagged as delayed (in-transit overlay)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentDelayed"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDelivered(DomainEvent):
<<<<<<< HEAD
    """Shipment delivered (terminal)."""
=======
    """Shipment reached its destination (in_transit/delayed → delivered, terminal)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentDelivered"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    delivered_at: Optional[str]
    previous_status: str
    # Sprint 12 enrichment (additive, v1-compatible): timing for on-time/late +
    # delivery-duration analytics. Older payloads omit these (deserialize as None).
    planned_delivery_at: Optional[str] = None
    picked_up_at: Optional[str] = None
    delay_minutes: Optional[int] = None
    order_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentFailed(DomainEvent):
<<<<<<< HEAD
    """Delivery attempt failed (may be followed by a return)."""
=======
    """Shipment delivery failed (in-progress → failed)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentFailed"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentReturned(DomainEvent):
<<<<<<< HEAD
    """Shipment returned to origin (terminal)."""
=======
    """Shipment was returned to origin (in-progress/failed → returned, terminal)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentReturned"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentCancelled(DomainEvent):
<<<<<<< HEAD
    """Shipment cancelled (terminal). ``compensation_required`` is True when
    cancelling after resources were committed (assigned/picked_up/in_transit/delayed)."""
=======
    """Shipment was cancelled (any pre-delivery → cancelled, terminal).

    ``compensation_required`` is True when cancelling from a committed state
    (assigned / picked_up / in_transit / delayed), signalling downstream
    compensation workflows.
    """
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

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
<<<<<<< HEAD
    """Mutable shipment fields changed."""
=======
    """Mutable shipment fields were modified."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentUpdated"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDeleted(DomainEvent):
<<<<<<< HEAD
    """Shipment soft-deleted."""
=======
    """Shipment was soft-deleted (logical removal only)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentDeleted"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    deleted_by: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentRestored(DomainEvent):
<<<<<<< HEAD
    """Soft-deleted shipment restored."""
=======
    """A previously soft-deleted shipment was restored."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentRestored"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentAddressChanged(DomainEvent):
<<<<<<< HEAD
    """Origin/destination warehouse routing changed."""
=======
    """Origin/destination warehouse changed."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentAddressChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentCargoChanged(DomainEvent):
<<<<<<< HEAD
    """Cargo attributes (weight/volume/type/description) changed."""
=======
    """Cargo metadata (type / description / weight / volume) changed."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentCargoChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentDriverChanged(DomainEvent):
<<<<<<< HEAD
    """Assigned driver changed (assignment or reassignment)."""
=======
    """Assigned driver changed (reassignment)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

    event_type = "ShipmentDriverChanged"
    event_version = 1

    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_driver_id: Optional[uuid.UUID]
    new_driver_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ShipmentVehicleChanged(DomainEvent):
<<<<<<< HEAD
    """Assigned vehicle changed (assignment or reassignment)."""
=======
    """Assigned vehicle changed (reassignment)."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

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
