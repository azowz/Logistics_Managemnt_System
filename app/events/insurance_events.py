"""Insurance & Claims domain events (context #17, Sprint 8).

Frozen, slotted dataclasses registered on the process-wide registry. Naming
``<Aggregate><PastTenseVerb>`` (ADR-007). Business payload only; envelope
metadata is added by :class:`~app.events.envelope.EventEnvelope`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.events.domain_event import DomainEvent
from app.events.registry import register_event


# --- Insurance policy ------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class InsurancePolicyCreated(DomainEvent):
    event_type = "InsurancePolicyCreated"
    event_version = 1
    policy_id: uuid.UUID
    tenant_id: uuid.UUID
    policy_number: str
    policy_type: str
    status: str


@register_event
@dataclass(frozen=True, slots=True)
class InsurancePolicyActivated(DomainEvent):
    event_type = "InsurancePolicyActivated"
    event_version = 1
    policy_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class InsurancePolicySuspended(DomainEvent):
    event_type = "InsurancePolicySuspended"
    event_version = 1
    policy_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class InsurancePolicyExpired(DomainEvent):
    event_type = "InsurancePolicyExpired"
    event_version = 1
    policy_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class InsurancePolicyCancelled(DomainEvent):
    event_type = "InsurancePolicyCancelled"
    event_version = 1
    policy_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class CoverageRuleCreated(DomainEvent):
    event_type = "CoverageRuleCreated"
    event_version = 1
    rule_id: uuid.UUID
    tenant_id: uuid.UUID
    policy_id: uuid.UUID
    coverage_type: str


@register_event
@dataclass(frozen=True, slots=True)
class CoverageRuleUpdated(DomainEvent):
    event_type = "CoverageRuleUpdated"
    event_version = 1
    rule_id: uuid.UUID
    tenant_id: uuid.UUID
    changed_fields: Dict[str, Any]


# --- Claim lifecycle -------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class ClaimCreated(DomainEvent):
    event_type = "ClaimCreated"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    claim_number: str
    claim_type: str
    status: str
    shipment_id: Optional[uuid.UUID]
    equipment_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ClaimSubmittedForReview(DomainEvent):
    event_type = "ClaimSubmittedForReview"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ClaimApproved(DomainEvent):
    event_type = "ClaimApproved"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    approved_amount: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ClaimRejected(DomainEvent):
    event_type = "ClaimRejected"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ClaimSettled(DomainEvent):
    event_type = "ClaimSettled"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    approved_amount: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ClaimClosed(DomainEvent):
    event_type = "ClaimClosed"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class ClaimReopened(DomainEvent):
    event_type = "ClaimReopened"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ClaimDeleted(DomainEvent):
    event_type = "ClaimDeleted"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    deleted_by: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ClaimRestored(DomainEvent):
    event_type = "ClaimRestored"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class DamageReportCreated(DomainEvent):
    event_type = "DamageReportCreated"
    event_version = 1
    damage_report_id: uuid.UUID
    tenant_id: uuid.UUID
    claim_id: uuid.UUID
    damage_type: str


@register_event
@dataclass(frozen=True, slots=True)
class LiabilityRecordCreated(DomainEvent):
    event_type = "LiabilityRecordCreated"
    event_version = 1
    liability_record_id: uuid.UUID
    tenant_id: uuid.UUID
    claim_id: uuid.UUID
    responsible_party_type: str
    liability_percentage: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class ClaimLinkedToShipment(DomainEvent):
    event_type = "ClaimLinkedToShipment"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    shipment_id: uuid.UUID


@register_event
@dataclass(frozen=True, slots=True)
class ClaimLinkedToEquipment(DomainEvent):
    event_type = "ClaimLinkedToEquipment"
    event_version = 1
    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    equipment_id: uuid.UUID


__all__ = [
    "InsurancePolicyCreated",
    "InsurancePolicyActivated",
    "InsurancePolicySuspended",
    "InsurancePolicyExpired",
    "InsurancePolicyCancelled",
    "CoverageRuleCreated",
    "CoverageRuleUpdated",
    "ClaimCreated",
    "ClaimSubmittedForReview",
    "ClaimApproved",
    "ClaimRejected",
    "ClaimSettled",
    "ClaimClosed",
    "ClaimReopened",
    "ClaimDeleted",
    "ClaimRestored",
    "DamageReportCreated",
    "LiabilityRecordCreated",
    "ClaimLinkedToShipment",
    "ClaimLinkedToEquipment",
]
