"""Unit tests for the Permit lifecycle state machine."""

from __future__ import annotations

import pytest

from app.models.enums import PermitStatus as P
from app.services.compliance_policies import PermitStateMachine as SM
from app.services.exceptions import StatusTransitionError

VALID = [
    (P.DRAFT, P.SUBMITTED), (P.DRAFT, P.CANCELLED),
    (P.SUBMITTED, P.UNDER_REVIEW), (P.SUBMITTED, P.CANCELLED),
    (P.UNDER_REVIEW, P.APPROVED), (P.UNDER_REVIEW, P.REJECTED), (P.UNDER_REVIEW, P.CANCELLED),
    (P.APPROVED, P.ACTIVE), (P.APPROVED, P.CANCELLED),
    (P.ACTIVE, P.EXPIRED), (P.ACTIVE, P.CANCELLED),
]
INVALID = [
    (P.DRAFT, P.APPROVED), (P.DRAFT, P.ACTIVE),
    (P.SUBMITTED, P.APPROVED), (P.APPROVED, P.EXPIRED),
    (P.REJECTED, P.ACTIVE), (P.EXPIRED, P.ACTIVE), (P.CANCELLED, P.DRAFT),
    (P.UNDER_REVIEW, P.ACTIVE),
]


@pytest.mark.parametrize("cur,tgt", VALID)
def test_valid(cur, tgt):
    assert SM.can_transition(cur, tgt)
    SM.validate_transition(cur, tgt)


@pytest.mark.parametrize("cur,tgt", INVALID)
def test_invalid(cur, tgt):
    assert not SM.can_transition(cur, tgt)
    with pytest.raises(StatusTransitionError):
        SM.validate_transition(cur, tgt)


@pytest.mark.parametrize("s", [P.REJECTED, P.EXPIRED, P.CANCELLED])
def test_terminal(s):
    assert SM.is_terminal(s)
    assert SM.ALLOWED_TRANSITIONS[s] == frozenset()


def test_only_active_is_dispatchable():
    assert SM.is_dispatchable(P.ACTIVE)
    for s in (P.DRAFT, P.SUBMITTED, P.UNDER_REVIEW, P.APPROVED, P.EXPIRED, P.CANCELLED, P.REJECTED):
        assert not SM.is_dispatchable(s)
