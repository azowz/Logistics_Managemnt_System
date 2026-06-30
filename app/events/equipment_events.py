"""Equipment & Asset domain events (context #15, Sprint 6).

All events are frozen, slotted dataclasses registered on the process-wide
registry via ``@register_event``. Naming follows ``Equipment<PastTenseVerb>``
(ADR-007). Each carries only the business payload; envelope metadata is added by
:class:`~app.events.envelope.EventEnvelope`.

``tenant_id`` is duplicated in the payload to stay consistent with the
customer/order/shipment precedent (also present on the envelope).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.events.domain_event import DomainEvent
from app.events.registry import register_event


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentCreated(DomainEvent):
    """A new equipment unit was onboarded (status=active)."""

    event_type = "EquipmentCreated"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    equipment_code: str
    asset_tag: str
    category_id: uuid.UUID
    model_id: Optional[uuid.UUID]
    status: str
    availability_status: str
    ownership_type: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentUpdated(DomainEvent):
    """Mutable equipment fields were modified."""

    event_type = "EquipmentUpdated"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentActivated(DomainEvent):
    """Equipment returned to active service."""

    event_type = "EquipmentActivated"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentDeactivated(DomainEvent):
    """Equipment was deactivated (active → inactive)."""

    event_type = "EquipmentDeactivated"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentReserved(DomainEvent):
    """Equipment unit was reserved for a job/order."""

    event_type = "EquipmentReserved"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reference: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentReleased(DomainEvent):
    """A reservation was released; unit returns to available."""

    event_type = "EquipmentReleased"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentAssignedToShipment(DomainEvent):
    """Equipment was bound to a shipment for movement."""

    event_type = "EquipmentAssignedToShipment"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    shipment_id: uuid.UUID
    previous_availability: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentInTransit(DomainEvent):
    """Equipment entered transit (carrying shipment reached in_transit)."""

    event_type = "EquipmentInTransit"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentDelivered(DomainEvent):
    """Equipment movement completed (carrying shipment delivered)."""

    event_type = "EquipmentDelivered"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentMaintenanceStarted(DomainEvent):
    """Equipment entered maintenance (temporary out-of-service)."""

    event_type = "EquipmentMaintenanceStarted"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentMaintenanceCompleted(DomainEvent):
    """Maintenance completed; unit returns to active."""

    event_type = "EquipmentMaintenanceCompleted"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentDecommissioned(DomainEvent):
    """Equipment was permanently decommissioned (terminal)."""

    event_type = "EquipmentDecommissioned"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentDeleted(DomainEvent):
    """Equipment was soft-deleted (logical removal only)."""

    event_type = "EquipmentDeleted"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    deleted_by: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentRestored(DomainEvent):
    """A previously soft-deleted equipment unit was restored."""

    event_type = "EquipmentRestored"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentStatusChanged(DomainEvent):
    """General status-transition event (captures every status change)."""

    event_type = "EquipmentStatusChanged"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    new_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentAvailabilityChanged(DomainEvent):
    """Equipment availability status changed (independent of lifecycle status)."""

    event_type = "EquipmentAvailabilityChanged"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_availability: str
    new_availability: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentCategoryCreated(DomainEvent):
    """A new equipment category (taxonomy node) was created."""

    event_type = "EquipmentCategoryCreated"
    event_version = 1

    category_id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentModelCreated(DomainEvent):
    """A new equipment model (catalog entry) was created."""

    event_type = "EquipmentModelCreated"
    event_version = 1

    model_id: uuid.UUID
    tenant_id: uuid.UUID
    category_id: uuid.UUID
    code: str
    name: str


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentLocationChanged(DomainEvent):
    """Equipment current warehouse / location changed."""

    event_type = "EquipmentLocationChanged"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


@register_event
@dataclass(frozen=True, slots=True)
class EquipmentSpecificationChanged(DomainEvent):
    """Equipment dimensions/weight/transport-requirement flags changed."""

    event_type = "EquipmentSpecificationChanged"
    event_version = 1

    equipment_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


__all__ = [
    "EquipmentCreated",
    "EquipmentUpdated",
    "EquipmentActivated",
    "EquipmentDeactivated",
    "EquipmentReserved",
    "EquipmentReleased",
    "EquipmentAssignedToShipment",
    "EquipmentInTransit",
    "EquipmentDelivered",
    "EquipmentMaintenanceStarted",
    "EquipmentMaintenanceCompleted",
    "EquipmentDecommissioned",
    "EquipmentDeleted",
    "EquipmentRestored",
    "EquipmentStatusChanged",
    "EquipmentAvailabilityChanged",
    "EquipmentLocationChanged",
    "EquipmentSpecificationChanged",
    "EquipmentCategoryCreated",
    "EquipmentModelCreated",
]
