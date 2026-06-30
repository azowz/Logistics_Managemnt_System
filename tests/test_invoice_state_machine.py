"""Tests for InvoiceStateMachine transitions (Sprint 9)."""

from __future__ import annotations

import pytest

from app.models.enums import InvoiceStatus
from app.services.billing_policies import InvoiceStateMachine
from app.services.exceptions import StatusTransitionError


def test_happy_path_transitions():
    assert InvoiceStateMachine.can_transition(InvoiceStatus.DRAFT, InvoiceStatus.ISSUED)
    assert InvoiceStateMachine.can_transition(InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)
    assert InvoiceStateMachine.can_transition(InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID)
    assert InvoiceStateMachine.can_transition(InvoiceStatus.ISSUED, InvoiceStatus.PAID)
    assert InvoiceStateMachine.can_transition(InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE)
    assert InvoiceStateMachine.can_transition(InvoiceStatus.ISSUED, InvoiceStatus.VOIDED)
    assert InvoiceStateMachine.can_transition(InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID)
    assert InvoiceStateMachine.can_transition(InvoiceStatus.OVERDUE, InvoiceStatus.PARTIALLY_PAID)
    assert InvoiceStateMachine.can_transition(InvoiceStatus.OVERDUE, InvoiceStatus.PAID)


@pytest.mark.parametrize("terminal", [InvoiceStatus.PAID, InvoiceStatus.VOIDED, InvoiceStatus.CANCELLED])
def test_terminal_states(terminal):
    assert InvoiceStateMachine.is_terminal(terminal)
    assert not InvoiceStateMachine.ALLOWED_TRANSITIONS[terminal]


def test_illegal_transitions_raise():
    with pytest.raises(StatusTransitionError):
        InvoiceStateMachine.validate_transition(InvoiceStatus.DRAFT, InvoiceStatus.PAID)
    with pytest.raises(StatusTransitionError):
        InvoiceStateMachine.validate_transition(InvoiceStatus.PAID, InvoiceStatus.VOIDED)
    with pytest.raises(StatusTransitionError):
        InvoiceStateMachine.validate_transition(InvoiceStatus.DRAFT, InvoiceStatus.OVERDUE)


def test_partially_paid_cannot_be_voided():
    assert not InvoiceStateMachine.can_transition(InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.VOIDED)
