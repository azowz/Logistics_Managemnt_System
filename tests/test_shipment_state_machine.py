"""Unit tests for the Shipment lifecycle state machine."""

from __future__ import annotations

import pytest

from app.models.enums import ShipmentStatus as S
from app.services.exceptions import StatusTransitionError
from app.services.shipment_policies import ShipmentStateMachine as SM

VALID = [
    (S.CREATED, S.READY),
    (S.CREATED, S.CANCELLED),
    (S.READY, S.ASSIGNED),
    (S.READY, S.CANCELLED),
    (S.ASSIGNED, S.PICKED_UP),
    (S.ASSIGNED, S.CANCELLED),
    (S.ASSIGNED, S.FAILED),
    (S.PICKED_UP, S.IN_TRANSIT),
    (S.PICKED_UP, S.FAILED),
    (S.IN_TRANSIT, S.DELAYED),
    (S.IN_TRANSIT, S.DELIVERED),
    (S.IN_TRANSIT, S.FAILED),
    (S.IN_TRANSIT, S.RETURNED),
    (S.IN_TRANSIT, S.CANCELLED),
    (S.DELAYED, S.IN_TRANSIT),
    (S.DELAYED, S.DELIVERED),
    (S.FAILED, S.RETURNED),
]

INVALID = [
    (S.CREATED, S.ASSIGNED),
    (S.CREATED, S.IN_TRANSIT),
    (S.CREATED, S.DELIVERED),
    (S.READY, S.PICKED_UP),
    (S.READY, S.IN_TRANSIT),
    (S.ASSIGNED, S.IN_TRANSIT),  # must pick up first
    (S.ASSIGNED, S.DELIVERED),
    (S.PICKED_UP, S.DELIVERED),  # must be in transit first
    (S.DELIVERED, S.CANCELLED),
    (S.CANCELLED, S.READY),
    (S.RETURNED, S.IN_TRANSIT),
    (S.FAILED, S.DELIVERED),
    (S.FAILED, S.CANCELLED),
]


@pytest.mark.parametrize("current,target", VALID)
def test_valid_transitions(current, target):
    assert SM.can_transition(current, target) is True
    SM.validate_transition(current, target)  # must not raise


@pytest.mark.parametrize("current,target", INVALID)
def test_invalid_transitions(current, target):
    assert SM.can_transition(current, target) is False
    with pytest.raises(StatusTransitionError):
        SM.validate_transition(current, target)


@pytest.mark.parametrize(
    "status", [S.DELIVERED, S.CANCELLED, S.RETURNED, S.FAILED]
)
def test_terminal_states(status):
    assert SM.is_terminal(status) is True


@pytest.mark.parametrize(
    "status", [S.CREATED, S.READY, S.ASSIGNED, S.PICKED_UP, S.IN_TRANSIT, S.DELAYED]
)
def test_non_terminal_states(status):
    assert SM.is_terminal(status) is False


def test_delivered_has_no_outgoing_transitions():
    assert SM.ALLOWED_TRANSITIONS[S.DELIVERED] == frozenset()


def test_failed_allows_only_return():
    assert SM.ALLOWED_TRANSITIONS[S.FAILED] == frozenset({S.RETURNED})


@pytest.mark.parametrize(
    "previous,expected",
    [
        (S.CREATED, False),
        (S.READY, False),
        (S.ASSIGNED, True),
        (S.PICKED_UP, True),
        (S.IN_TRANSIT, True),
        (S.DELAYED, True),
    ],
)
def test_requires_compensation(previous, expected):
    assert SM.requires_compensation(previous) is expected


def test_delayed_is_overlay_not_terminal():
    # delayed can resume to in_transit and reach delivered.
    assert SM.can_transition(S.DELAYED, S.IN_TRANSIT)
    assert SM.can_transition(S.DELAYED, S.DELIVERED)
    assert not SM.is_terminal(S.DELAYED)
