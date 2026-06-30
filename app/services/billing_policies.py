"""Billing & Settlements domain policies — Quote / Invoice / Settlement state
machines (context #18, Sprint 9).

Single source of truth for transitions, mirroring the other domains. Services
delegate every status change here.

Quote::
    draft → issued → {approved, rejected, expired, cancelled}
    approved → cancelled
  Terminal: rejected, expired, cancelled.

Invoice::
    draft → {issued, cancelled}
    issued → {partially_paid, paid, overdue, voided, cancelled}
    partially_paid → paid
    overdue → {partially_paid, paid}
  Terminal: paid, voided, cancelled.

Settlement::
    draft → pending_approval → approved → settled
    {draft, pending_approval, approved} → cancelled
  Terminal: settled, cancelled.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.models.enums import InvoiceStatus, QuoteStatus, SettlementStatus
from app.services.exceptions import StatusTransitionError


class QuoteStateMachine:
    """Validates and describes Quote status transitions."""

    ALLOWED_TRANSITIONS: Dict[QuoteStatus, FrozenSet[QuoteStatus]] = {
        QuoteStatus.DRAFT: frozenset({QuoteStatus.ISSUED}),
        QuoteStatus.ISSUED: frozenset(
            {
                QuoteStatus.APPROVED,
                QuoteStatus.REJECTED,
                QuoteStatus.EXPIRED,
                QuoteStatus.CANCELLED,
            }
        ),
        QuoteStatus.APPROVED: frozenset({QuoteStatus.CANCELLED}),
        QuoteStatus.REJECTED: frozenset(),
        QuoteStatus.EXPIRED: frozenset(),
        QuoteStatus.CANCELLED: frozenset(),
    }

    TERMINAL_STATES: FrozenSet[QuoteStatus] = frozenset(
        {QuoteStatus.REJECTED, QuoteStatus.EXPIRED, QuoteStatus.CANCELLED}
    )

    @classmethod
    def is_terminal(cls, status: QuoteStatus) -> bool:
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: QuoteStatus, target: QuoteStatus) -> bool:
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: QuoteStatus, target: QuoteStatus) -> None:
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition quote from '{current.value}' to '{target.value}'."
            )


class InvoiceStateMachine:
    """Validates and describes Invoice status transitions."""

    ALLOWED_TRANSITIONS: Dict[InvoiceStatus, FrozenSet[InvoiceStatus]] = {
        InvoiceStatus.DRAFT: frozenset({InvoiceStatus.ISSUED, InvoiceStatus.CANCELLED}),
        InvoiceStatus.ISSUED: frozenset(
            {
                InvoiceStatus.PARTIALLY_PAID,
                InvoiceStatus.PAID,
                InvoiceStatus.OVERDUE,
                InvoiceStatus.VOIDED,
                InvoiceStatus.CANCELLED,
            }
        ),
        InvoiceStatus.PARTIALLY_PAID: frozenset({InvoiceStatus.PAID, InvoiceStatus.OVERDUE}),
        InvoiceStatus.OVERDUE: frozenset({InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID}),
        InvoiceStatus.PAID: frozenset(),
        InvoiceStatus.VOIDED: frozenset(),
        InvoiceStatus.CANCELLED: frozenset(),
    }

    TERMINAL_STATES: FrozenSet[InvoiceStatus] = frozenset(
        {InvoiceStatus.PAID, InvoiceStatus.VOIDED, InvoiceStatus.CANCELLED}
    )

    @classmethod
    def is_terminal(cls, status: InvoiceStatus) -> bool:
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: InvoiceStatus, target: InvoiceStatus) -> bool:
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: InvoiceStatus, target: InvoiceStatus) -> None:
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition invoice from '{current.value}' to '{target.value}'."
            )


class SettlementStateMachine:
    """Validates and describes Settlement status transitions."""

    ALLOWED_TRANSITIONS: Dict[SettlementStatus, FrozenSet[SettlementStatus]] = {
        SettlementStatus.DRAFT: frozenset(
            {SettlementStatus.PENDING_APPROVAL, SettlementStatus.CANCELLED}
        ),
        SettlementStatus.PENDING_APPROVAL: frozenset(
            {SettlementStatus.APPROVED, SettlementStatus.CANCELLED}
        ),
        SettlementStatus.APPROVED: frozenset(
            {SettlementStatus.SETTLED, SettlementStatus.CANCELLED}
        ),
        SettlementStatus.SETTLED: frozenset(),
        SettlementStatus.CANCELLED: frozenset(),
    }

    TERMINAL_STATES: FrozenSet[SettlementStatus] = frozenset(
        {SettlementStatus.SETTLED, SettlementStatus.CANCELLED}
    )

    @classmethod
    def is_terminal(cls, status: SettlementStatus) -> bool:
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: SettlementStatus, target: SettlementStatus) -> bool:
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: SettlementStatus, target: SettlementStatus) -> None:
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition settlement from '{current.value}' to '{target.value}'."
            )
