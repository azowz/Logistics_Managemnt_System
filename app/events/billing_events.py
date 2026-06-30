"""Billing & Settlements domain events (context #18, Sprint 9).

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


# --- Quote -----------------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class QuoteCreated(DomainEvent):
    event_type = "QuoteCreated"
    event_version = 1
    quote_id: uuid.UUID
    tenant_id: uuid.UUID
    quote_number: str
    status: str
    total_amount: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class QuoteIssued(DomainEvent):
    event_type = "QuoteIssued"
    event_version = 1
    quote_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class QuoteApproved(DomainEvent):
    event_type = "QuoteApproved"
    event_version = 1
    quote_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class QuoteRejected(DomainEvent):
    event_type = "QuoteRejected"
    event_version = 1
    quote_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class QuoteExpired(DomainEvent):
    event_type = "QuoteExpired"
    event_version = 1
    quote_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class QuoteCancelled(DomainEvent):
    event_type = "QuoteCancelled"
    event_version = 1
    quote_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


# --- Invoice ---------------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class InvoiceCreated(DomainEvent):
    event_type = "InvoiceCreated"
    event_version = 1
    invoice_id: uuid.UUID
    tenant_id: uuid.UUID
    invoice_number: str
    status: str
    total_amount: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class InvoiceIssued(DomainEvent):
    event_type = "InvoiceIssued"
    event_version = 1
    invoice_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    total_amount: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class InvoicePartiallyPaid(DomainEvent):
    event_type = "InvoicePartiallyPaid"
    event_version = 1
    invoice_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    balance: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class InvoicePaid(DomainEvent):
    event_type = "InvoicePaid"
    event_version = 1
    invoice_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class InvoiceOverdue(DomainEvent):
    event_type = "InvoiceOverdue"
    event_version = 1
    invoice_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class InvoiceVoided(DomainEvent):
    event_type = "InvoiceVoided"
    event_version = 1
    invoice_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class InvoiceCancelled(DomainEvent):
    event_type = "InvoiceCancelled"
    event_version = 1
    invoice_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


# --- Payment ---------------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class PaymentRecorded(DomainEvent):
    event_type = "PaymentRecorded"
    event_version = 1
    payment_id: uuid.UUID
    tenant_id: uuid.UUID
    invoice_id: uuid.UUID
    amount: str
    method: str


@register_event
@dataclass(frozen=True, slots=True)
class PaymentFailed(DomainEvent):
    event_type = "PaymentFailed"
    event_version = 1
    payment_id: uuid.UUID
    tenant_id: uuid.UUID
    invoice_id: uuid.UUID
    reason: Optional[str]


# --- Settlement ------------------------------------------------------------


@register_event
@dataclass(frozen=True, slots=True)
class SettlementCreated(DomainEvent):
    event_type = "SettlementCreated"
    event_version = 1
    settlement_id: uuid.UUID
    tenant_id: uuid.UUID
    settlement_number: str
    settlement_type: str
    status: str
    amount: Optional[str]
    claim_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class SettlementSubmittedForApproval(DomainEvent):
    event_type = "SettlementSubmittedForApproval"
    event_version = 1
    settlement_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class SettlementApproved(DomainEvent):
    event_type = "SettlementApproved"
    event_version = 1
    settlement_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str


@register_event
@dataclass(frozen=True, slots=True)
class SettlementSettled(DomainEvent):
    event_type = "SettlementSettled"
    event_version = 1
    settlement_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    amount: Optional[str]


@register_event
@dataclass(frozen=True, slots=True)
class SettlementCancelled(DomainEvent):
    event_type = "SettlementCancelled"
    event_version = 1
    settlement_id: uuid.UUID
    tenant_id: uuid.UUID
    previous_status: str
    reason: Optional[str]


# --- Payout / Penalty / Cancellation fee / Claim consumption ---------------


@register_event
@dataclass(frozen=True, slots=True)
class PayoutCreated(DomainEvent):
    event_type = "PayoutCreated"
    event_version = 1
    payout_id: uuid.UUID
    tenant_id: uuid.UUID
    settlement_id: uuid.UUID
    amount: str
    method: str


@register_event
@dataclass(frozen=True, slots=True)
class PenaltyApplied(DomainEvent):
    event_type = "PenaltyApplied"
    event_version = 1
    penalty_id: uuid.UUID
    tenant_id: uuid.UUID
    penalty_type: str
    amount: str
    order_id: Optional[uuid.UUID]
    shipment_id: Optional[uuid.UUID]
    invoice_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class CancellationFeeApplied(DomainEvent):
    event_type = "CancellationFeeApplied"
    event_version = 1
    penalty_id: uuid.UUID
    tenant_id: uuid.UUID
    amount: str
    order_id: Optional[uuid.UUID]
    shipment_id: Optional[uuid.UUID]


@register_event
@dataclass(frozen=True, slots=True)
class ClaimSettlementConsumed(DomainEvent):
    event_type = "ClaimSettlementConsumed"
    event_version = 1
    settlement_id: uuid.UUID
    tenant_id: uuid.UUID
    claim_id: uuid.UUID
    amount: Optional[str]


__all__ = [
    "QuoteCreated",
    "QuoteIssued",
    "QuoteApproved",
    "QuoteRejected",
    "QuoteExpired",
    "QuoteCancelled",
    "InvoiceCreated",
    "InvoiceIssued",
    "InvoicePartiallyPaid",
    "InvoicePaid",
    "InvoiceOverdue",
    "InvoiceVoided",
    "InvoiceCancelled",
    "PaymentRecorded",
    "PaymentFailed",
    "SettlementCreated",
    "SettlementSubmittedForApproval",
    "SettlementApproved",
    "SettlementSettled",
    "SettlementCancelled",
    "PayoutCreated",
    "PenaltyApplied",
    "CancellationFeeApplied",
    "ClaimSettlementConsumed",
]
