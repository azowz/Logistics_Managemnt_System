"""Compliance & Permits domain events (context #16, Sprint 7).

Frozen, slotted dataclasses registered on the process-wide registry. Naming
``<Aggregate><PastTenseVerb>`` (ADR-007). Business payload only; envelope
metadata is added by :class:`~app.events.envelope.EventEnvelope`. ``tenant_id``
is duplicated in payloads to match the established precedent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.events.domain_event import DomainEvent
from app.events.registry import register_event


# --- Permit lifecycle -----------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class PermitCreated(DomainEvent):
    event_type = "PermitCreated"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    permit_number: str
    permit_type: str
    status: str
    shipment_id: Optional[uuid.UUID]
    equipment_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class PermitSubmitted(DomainEvent):
    event_type = "PermitSubmitted"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class PermitUnderReview(DomainEvent):
    event_type = "PermitUnderReview"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class PermitApproved(DomainEvent):
    event_type = "PermitApproved"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    valid_from: Optional[str]
    valid_until: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class PermitRejected(DomainEvent):
    event_type = "PermitRejected"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class PermitActivated(DomainEvent):
    event_type = "PermitActivated"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class PermitExpired(DomainEvent):
    event_type = "PermitExpired"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class PermitCancelled(DomainEvent):
    event_type = "PermitCancelled"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class PermitDeleted(DomainEvent):
    event_type = "PermitDeleted"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID
    deleted_by: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class PermitRestored(DomainEvent):
    event_type = "PermitRestored"
    event_version = 1
    permit_id: uuid.UUID
    tenant_id: uuid.UUID


# --- Escort ----------------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class EscortCreated(DomainEvent):
    event_type = "EscortCreated"
    event_version = 1
    escort_id: uuid.UUID
    tenant_id: uuid.UUID
    escort_type: str
    shipment_id: Optional[uuid.UUID]
    permit_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class EscortScheduled(DomainEvent):
    event_type = "EscortScheduled"
    event_version = 1
    escort_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class EscortCancelled(DomainEvent):
    event_type = "EscortCancelled"
    event_version = 1
    escort_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


# --- Route restriction -----------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class RouteRestrictionCreated(DomainEvent):
    event_type = "RouteRestrictionCreated"
    event_version = 1
    restriction_id: uuid.UUID
    tenant_id: uuid.UUID
    restriction_type: str
    region: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class RouteRestrictionUpdated(DomainEvent):
    event_type = "RouteRestrictionUpdated"
    event_version = 1
    restriction_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


# --- Axle weight -----------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class AxleWeightProfileCreated(DomainEvent):
    event_type = "AxleWeightProfileCreated"
    event_version = 1
    profile_id: uuid.UUID
    tenant_id: uuid.UUID
    equipment_id: Optional[uuid.UUID]
    vehicle_id: Optional[uuid.UUID]
    is_compliant: bool


# --- Compliance checks -----------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class ComplianceCheckCreated(DomainEvent):
    event_type = "ComplianceCheckCreated"
    event_version = 1
    check_id: uuid.UUID
    tenant_id: uuid.UUID
    shipment_id: Optional[uuid.UUID]
    check_type: str
    status: str


@register_event
@dataclass(frozen=True, slots=True)
class ComplianceCheckPassed(DomainEvent):
    event_type = "ComplianceCheckPassed"
    event_version = 1
    check_id: uuid.UUID
    tenant_id: uuid.UUID
    shipment_id: Optional[uuid.UUID]
    check_type: str


@register_event
@dataclass(frozen=True, slots=True)
class ComplianceCheckFailed(DomainEvent):
    event_type = "ComplianceCheckFailed"
    event_version = 1
    check_id: uuid.UUID
    tenant_id: uuid.UUID
    shipment_id: Optional[uuid.UUID]
    check_type: str
    failure_reasons: List[Any]


@register_event
@dataclass(frozen=True, slots=True)
class ComplianceOverrideApplied(DomainEvent):
    event_type = "ComplianceOverrideApplied"
    event_version = 1
    check_id: uuid.UUID
    tenant_id: uuid.UUID
    overridden_by: Optional[uuid.UUID]
    reason: Optional[str]


# --- Operator certification ------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class OperatorCertificationCreated(DomainEvent):
    event_type = "OperatorCertificationCreated"
    event_version = 1
    certification_id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    certification_type: str
    status: str


@register_event
@dataclass(frozen=True, slots=True)
class OperatorCertificationExpired(DomainEvent):
    event_type = "OperatorCertificationExpired"
    event_version = 1
    certification_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


# --- Dispatch gate ---------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class DispatchBlockedByCompliance(DomainEvent):
    event_type = "DispatchBlockedByCompliance"
    event_version = 1
    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    stage: str
    blocking_reasons: List[Any]


@register_event
@dataclass(frozen=True, slots=True)
class DispatchClearedByCompliance(DomainEvent):
    event_type = "DispatchClearedByCompliance"
    event_version = 1
    shipment_id: uuid.UUID
    tenant_id: uuid.UUID
    stage: str


__all__ = [
    "PermitCreated",
    "PermitSubmitted",
    "PermitUnderReview",
    "PermitApproved",
    "PermitRejected",
    "PermitActivated",
    "PermitExpired",
    "PermitCancelled",
    "PermitDeleted",
    "PermitRestored",
    "EscortCreated",
    "EscortScheduled",
    "EscortCancelled",
    "RouteRestrictionCreated",
    "RouteRestrictionUpdated",
    "AxleWeightProfileCreated",
    "ComplianceCheckCreated",
    "ComplianceCheckPassed",
    "ComplianceCheckFailed",
    "ComplianceOverrideApplied",
    "OperatorCertificationCreated",
    "OperatorCertificationExpired",
    "DispatchBlockedByCompliance",
    "DispatchClearedByCompliance",
]
