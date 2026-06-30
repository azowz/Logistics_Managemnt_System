"""Equipment domain policies — the lifecycle state machine (Sprint 6).

Single, testable source of truth for Equipment status transitions, mirroring
``OrderStateMachine`` / ``ShipmentStateMachine``. The service delegates every
status change through :class:`EquipmentStateMachine`.

Status lifecycle (Sprint 6 authoritative set; a simplification of the richer
docs/08 Part 6 design — ``decommissioned`` ≈ OutOfService is terminal)::

    active ⇄ under_maintenance
    active ⇄ reserved → in_transit → active
    active ⇄ inactive → decommissioned
    active → decommissioned
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.models.enums import EquipmentAvailability, EquipmentStatus
from app.services.exceptions import StatusTransitionError


class EquipmentStateMachine:
    """Validates and describes Equipment status transitions."""

    ALLOWED_TRANSITIONS: Dict[EquipmentStatus, FrozenSet[EquipmentStatus]] = {
        EquipmentStatus.ACTIVE: frozenset(
            {
                EquipmentStatus.UNDER_MAINTENANCE,
                EquipmentStatus.RESERVED,
                EquipmentStatus.IN_TRANSIT,
                EquipmentStatus.INACTIVE,
                EquipmentStatus.DECOMMISSIONED,
            }
        ),
        EquipmentStatus.UNDER_MAINTENANCE: frozenset({EquipmentStatus.ACTIVE}),
        EquipmentStatus.RESERVED: frozenset(
            {EquipmentStatus.ACTIVE, EquipmentStatus.IN_TRANSIT}
        ),
        EquipmentStatus.IN_TRANSIT: frozenset({EquipmentStatus.ACTIVE}),
        EquipmentStatus.INACTIVE: frozenset(
            {EquipmentStatus.ACTIVE, EquipmentStatus.DECOMMISSIONED}
        ),
        EquipmentStatus.DECOMMISSIONED: frozenset(),
    }

    #: Terminal status — no transition permitted out.
    TERMINAL_STATES: FrozenSet[EquipmentStatus] = frozenset(
        {EquipmentStatus.DECOMMISSIONED}
    )

    #: Statuses from which a unit may NOT be assigned to a movement.
    NON_ASSIGNABLE_STATES: FrozenSet[EquipmentStatus] = frozenset(
        {
            EquipmentStatus.INACTIVE,
            EquipmentStatus.UNDER_MAINTENANCE,
            EquipmentStatus.DECOMMISSIONED,
        }
    )

    @classmethod
    def is_terminal(cls, status: EquipmentStatus) -> bool:
        """Return ``True`` if no transition is allowed out of ``status``."""
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: EquipmentStatus, target: EquipmentStatus) -> bool:
        """Return ``True`` if ``current → target`` is a permitted transition."""
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(
        cls, current: EquipmentStatus, target: EquipmentStatus
    ) -> None:
        """Raise :exc:`StatusTransitionError` if ``current → target`` is illegal."""
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition equipment from '{current.value}' to '{target.value}'."
            )

    @classmethod
    def is_assignable(cls, status: EquipmentStatus) -> bool:
        """Return ``True`` if a unit in ``status`` may be assigned to a movement."""
        return status not in cls.NON_ASSIGNABLE_STATES
