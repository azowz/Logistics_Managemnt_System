"""Tests for QuoteStateMachine transitions (Sprint 9)."""

from __future__ import annotations

import pytest

from app.models.enums import QuoteStatus
from app.services.billing_policies import QuoteStateMachine
from app.services.exceptions import StatusTransitionError


def test_happy_path_transitions():
    assert QuoteStateMachine.can_transition(QuoteStatus.DRAFT, QuoteStatus.ISSUED)
    assert QuoteStateMachine.can_transition(QuoteStatus.ISSUED, QuoteStatus.APPROVED)
    assert QuoteStateMachine.can_transition(QuoteStatus.ISSUED, QuoteStatus.REJECTED)
    assert QuoteStateMachine.can_transition(QuoteStatus.ISSUED, QuoteStatus.EXPIRED)
    assert QuoteStateMachine.can_transition(QuoteStatus.ISSUED, QuoteStatus.CANCELLED)
    assert QuoteStateMachine.can_transition(QuoteStatus.APPROVED, QuoteStatus.CANCELLED)


@pytest.mark.parametrize("terminal", [QuoteStatus.REJECTED, QuoteStatus.EXPIRED, QuoteStatus.CANCELLED])
def test_terminal_states(terminal):
    assert QuoteStateMachine.is_terminal(terminal)
    assert not QuoteStateMachine.ALLOWED_TRANSITIONS[terminal]


def test_illegal_transition_raises():
    with pytest.raises(StatusTransitionError):
        QuoteStateMachine.validate_transition(QuoteStatus.DRAFT, QuoteStatus.APPROVED)
    with pytest.raises(StatusTransitionError):
        QuoteStateMachine.validate_transition(QuoteStatus.APPROVED, QuoteStatus.ISSUED)


def test_draft_cannot_go_terminal_directly():
    assert not QuoteStateMachine.can_transition(QuoteStatus.DRAFT, QuoteStatus.CANCELLED)
    assert not QuoteStateMachine.can_transition(QuoteStatus.DRAFT, QuoteStatus.REJECTED)
