"""Shipment domain policies — the lifecycle state machine.

Single source of truth for shipment status transitions, mirroring
:class:`~app.services.order_policies.OrderStateMachine`. ``ShipmentService``
delegates every status change through :class:`ShipmentStateMachine`.

Lifecycle::

    created → ready → assigned → picked_up → in_transit → delivered
                                     │           │   ▲
                                     │           ▼   │
                                     │        delayed ┘
                                     │           │
                                     └───────────┴──→ failed → returned
                                                  └──→ returned
    (cancel allowed from any pre-delivered state)

Terminal: ``delivered``, ``cancelled``, ``returned``. ``failed`` is semi-terminal
(only ``failed → returned`` for compensation). ``delayed`` is an overlay reachable
from ``picked_up``/``in_transit`` that resumes into the main lifecycle.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.models.enums import ShipmentStatus
from app.services.exceptions import StatusTransitionError

S = ShipmentStatus


class ShipmentStateMachine:
    """Validates and describes Shipment status transitions."""

    #: status → set of statuses reachable from it (excluding cancellation, which
    #: is handled uniformly via :meth:`can_cancel`).
    ALLOWED_TRANSITIONS: Dict[ShipmentStatus, FrozenSet[ShipmentStatus]] = {
        S.CREATED: frozenset({S.READY, S.CANCELLED}),
        S.READY: frozenset({S.ASSIGNED, S.CANCELLED}),
        S.ASSIGNED: frozenset({S.PICKED_UP, S.CANCELLED}),
        S.PICKED_UP: frozenset({S.IN_TRANSIT, S.DELAYED, S.CANCELLED}),
        S.IN_TRANSIT: frozenset(
            {S.DELIVERED, S.FAILED, S.RETURNED, S.DELAYED, S.CANCELLED}
        ),
        S.DELAYED: frozenset(
            {S.IN_TRANSIT, S.DELIVERED, S.FAILED, S.RETURNED, S.CANCELLED}
        ),
        S.DELIVERED: frozenset(),
        S.FAILED: frozenset({S.RETURNED}),  # compensation path only
        S.RETURNED: frozenset(),
        S.CANCELLED: frozenset(),
    }

    #: Fully terminal states — no transition and no edits permitted.
    TERMINAL_STATES: FrozenSet[ShipmentStatus] = frozenset(
        {S.DELIVERED, S.CANCELLED, S.RETURNED}
    )

    #: States from which a cancellation must record compensation metadata
    #: (resources were already committed).
    COMPENSATION_STATES: FrozenSet[ShipmentStatus] = frozenset(
        {S.ASSIGNED, S.PICKED_UP, S.IN_TRANSIT, S.DELAYED}
    )

    #: States from which cancellation is allowed (anything not yet delivered/terminal).
    CANCELLABLE_STATES: FrozenSet[ShipmentStatus] = frozenset(
        {S.CREATED, S.READY, S.ASSIGNED, S.PICKED_UP, S.IN_TRANSIT, S.DELAYED}
    )

    @classmethod
    def is_terminal(cls, status: ShipmentStatus) -> bool:
        """Return ``True`` if no transition/edit is allowed out of ``status``."""
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: ShipmentStatus, target: ShipmentStatus) -> bool:
        """Return ``True`` if ``current → target`` is a permitted transition."""
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(
        cls, current: ShipmentStatus, target: ShipmentStatus
    ) -> None:
        """Raise :exc:`StatusTransitionError` if ``current → target`` is illegal."""
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition shipment from '{current.value}' to '{target.value}'."
            )

    @classmethod
    def can_cancel(cls, current: ShipmentStatus) -> bool:
        """Return ``True`` if a shipment in ``current`` may be cancelled."""
        return current in cls.CANCELLABLE_STATES

    @classmethod
    def requires_compensation(cls, previous: ShipmentStatus) -> bool:
        """Return ``True`` if cancelling from ``previous`` needs compensation."""
        return previous in cls.COMPENSATION_STATES
