"""Unit tests for the Equipment lifecycle state machine."""

from __future__ import annotations

import pytest

from app.models.enums import EquipmentStatus as E
from app.services.equipment_policies import EquipmentStateMachine as SM
from app.services.exceptions import StatusTransitionError

VALID = [
    (E.ACTIVE, E.UNDER_MAINTENANCE),
    (E.ACTIVE, E.RESERVED),
    (E.ACTIVE, E.IN_TRANSIT),
    (E.ACTIVE, E.INACTIVE),
    (E.ACTIVE, E.DECOMMISSIONED),
    (E.UNDER_MAINTENANCE, E.ACTIVE),
    (E.RESERVED, E.ACTIVE),
    (E.RESERVED, E.IN_TRANSIT),
    (E.IN_TRANSIT, E.ACTIVE),
    (E.INACTIVE, E.ACTIVE),
    (E.INACTIVE, E.DECOMMISSIONED),
]

INVALID = [
    (E.UNDER_MAINTENANCE, E.RESERVED),
    (E.RESERVED, E.UNDER_MAINTENANCE),
    (E.IN_TRANSIT, E.RESERVED),
    (E.IN_TRANSIT, E.DECOMMISSIONED),
    (E.DECOMMISSIONED, E.ACTIVE),
    (E.DECOMMISSIONED, E.INACTIVE),
    (E.UNDER_MAINTENANCE, E.DECOMMISSIONED),
    (E.RESERVED, E.DECOMMISSIONED),
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


def test_decommissioned_terminal():
    assert SM.is_terminal(E.DECOMMISSIONED)
    assert SM.ALLOWED_TRANSITIONS[E.DECOMMISSIONED] == frozenset()


@pytest.mark.parametrize(
    "status,assignable",
    [
        (E.ACTIVE, True),
        (E.RESERVED, True),
        (E.IN_TRANSIT, True),
        (E.INACTIVE, False),
        (E.UNDER_MAINTENANCE, False),
        (E.DECOMMISSIONED, False),
    ],
)
def test_is_assignable(status, assignable):
    assert SM.is_assignable(status) is assignable


def test_non_terminal_states():
    for s in (E.ACTIVE, E.RESERVED, E.IN_TRANSIT, E.INACTIVE, E.UNDER_MAINTENANCE):
        assert not SM.is_terminal(s)
