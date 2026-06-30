"""Unit tests for the Claim and Policy state machines."""

from __future__ import annotations

import pytest

from app.models.enums import ClaimStatus as C, InsurancePolicyStatus as P
from app.services.insurance_policies import ClaimStateMachine, PolicyStateMachine
from app.services.exceptions import StatusTransitionError

CLAIM_VALID = [
    (C.CREATED, C.UNDER_REVIEW),
    (C.UNDER_REVIEW, C.APPROVED),
    (C.UNDER_REVIEW, C.REJECTED),
    (C.APPROVED, C.SETTLED),
    (C.SETTLED, C.CLOSED),
    (C.REJECTED, C.CLOSED),
    (C.CLOSED, C.UNDER_REVIEW),
]
CLAIM_INVALID = [
    (C.CREATED, C.APPROVED),
    (C.CREATED, C.SETTLED),
    (C.UNDER_REVIEW, C.SETTLED),
    (C.APPROVED, C.CLOSED),
    (C.APPROVED, C.REJECTED),
    (C.REJECTED, C.APPROVED),
    (C.SETTLED, C.APPROVED),
]


@pytest.mark.parametrize("cur,tgt", CLAIM_VALID)
def test_claim_valid(cur, tgt):
    assert ClaimStateMachine.can_transition(cur, tgt)
    ClaimStateMachine.validate_transition(cur, tgt)


@pytest.mark.parametrize("cur,tgt", CLAIM_INVALID)
def test_claim_invalid(cur, tgt):
    assert not ClaimStateMachine.can_transition(cur, tgt)
    with pytest.raises(StatusTransitionError):
        ClaimStateMachine.validate_transition(cur, tgt)


def test_claim_closed_is_terminal_but_reopenable():
    assert ClaimStateMachine.is_terminal(C.CLOSED)
    assert ClaimStateMachine.can_transition(C.CLOSED, C.UNDER_REVIEW)


POLICY_VALID = [
    (P.DRAFT, P.ACTIVE), (P.DRAFT, P.CANCELLED),
    (P.ACTIVE, P.SUSPENDED), (P.ACTIVE, P.EXPIRED), (P.ACTIVE, P.CANCELLED),
    (P.SUSPENDED, P.ACTIVE), (P.SUSPENDED, P.CANCELLED),
]
POLICY_INVALID = [
    (P.DRAFT, P.SUSPENDED), (P.DRAFT, P.EXPIRED),
    (P.EXPIRED, P.ACTIVE), (P.CANCELLED, P.ACTIVE),
]


@pytest.mark.parametrize("cur,tgt", POLICY_VALID)
def test_policy_valid(cur, tgt):
    assert PolicyStateMachine.can_transition(cur, tgt)


@pytest.mark.parametrize("cur,tgt", POLICY_INVALID)
def test_policy_invalid(cur, tgt):
    with pytest.raises(StatusTransitionError):
        PolicyStateMachine.validate_transition(cur, tgt)


def test_only_active_policy_can_cover():
    assert PolicyStateMachine.can_cover(P.ACTIVE)
    for s in (P.DRAFT, P.SUSPENDED, P.EXPIRED, P.CANCELLED):
        assert not PolicyStateMachine.can_cover(s)
