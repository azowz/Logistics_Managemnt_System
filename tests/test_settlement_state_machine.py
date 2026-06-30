"""Tests for SettlementStateMachine transitions (Sprint 9)."""

from __future__ import annotations

import pytest

from app.models.enums import SettlementStatus
from app.services.billing_policies import SettlementStateMachine
from app.services.exceptions import StatusTransitionError


def test_happy_path_transitions():
    assert SettlementStateMachine.can_transition(SettlementStatus.DRAFT, SettlementStatus.PENDING_APPROVAL)
    assert SettlementStateMachine.can_transition(SettlementStatus.PENDING_APPROVAL, SettlementStatus.APPROVED)
    assert SettlementStateMachine.can_transition(SettlementStatus.APPROVED, SettlementStatus.SETTLED)


@pytest.mark.parametrize("src", [SettlementStatus.DRAFT, SettlementStatus.PENDING_APPROVAL, SettlementStatus.APPROVED])
def test_cancellable_from_non_terminal(src):
    assert SettlementStateMachine.can_transition(src, SettlementStatus.CANCELLED)


@pytest.mark.parametrize("terminal", [SettlementStatus.SETTLED, SettlementStatus.CANCELLED])
def test_terminal_states(terminal):
    assert SettlementStateMachine.is_terminal(terminal)
    assert not SettlementStateMachine.ALLOWED_TRANSITIONS[terminal]


def test_cannot_settle_before_approval():
    with pytest.raises(StatusTransitionError):
        SettlementStateMachine.validate_transition(SettlementStatus.PENDING_APPROVAL, SettlementStatus.SETTLED)
    with pytest.raises(StatusTransitionError):
        SettlementStateMachine.validate_transition(SettlementStatus.DRAFT, SettlementStatus.SETTLED)


def test_settled_is_final():
    with pytest.raises(StatusTransitionError):
        SettlementStateMachine.validate_transition(SettlementStatus.SETTLED, SettlementStatus.CANCELLED)
