<<<<<<< HEAD
"""Shipment domain policies — the lifecycle state machine.

Single source of truth for shipment status transitions, mirroring
:class:`~app.services.order_policies.OrderStateMachine`. ``ShipmentService``
delegates every status change through :class:`ShipmentStateMachine`.
=======
"""Shipment domain policies — the lifecycle state machine (Sprint 5).

Separated from :class:`~app.services.shipment_service.ShipmentService` so the
transition rules are a single, testable source of truth (SRP), mirroring
:class:`~app.services.order_policies.OrderStateMachine`. The service delegates
every status change through :class:`ShipmentStateMachine`.
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

Lifecycle::

    created → ready → assigned → picked_up → in_transit → delivered
<<<<<<< HEAD
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
=======
                                                  │  ▲
                                                  ▼  │
                                               delayed
    in-progress ──────────────────────────────────────→ failed → returned
    any pre-delivery ─────────────────────────────────→ cancelled

Rules (docs/19):
  * ``delivered``, ``cancelled`` and ``returned`` are terminal.
  * ``failed`` permits a single follow-on transition to ``returned`` (return /
    compensation); otherwise it is terminal.
  * assignment requires a driver *and* a vehicle (enforced by the service).
  * pickup requires assignment; in_transit requires pickup; delivery requires
    transit (or a delayed shipment resuming).
  * ``delayed`` is an in-transit overlay — it never advances the lifecycle and
    can resume back to ``in_transit`` or proceed to a terminal outcome.
  * cancellation is allowed before delivery; cancelling from a committed state
    (assigned/picked_up/in_transit/delayed) requires compensation metadata.
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.models.enums import ShipmentStatus
from app.services.exceptions import StatusTransitionError

<<<<<<< HEAD
S = ShipmentStatus

=======
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49

class ShipmentStateMachine:
    """Validates and describes Shipment status transitions."""

<<<<<<< HEAD
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
=======
    #: status → set of statuses reachable from it.
    ALLOWED_TRANSITIONS: Dict[ShipmentStatus, FrozenSet[ShipmentStatus]] = {
        ShipmentStatus.CREATED: frozenset({ShipmentStatus.READY, ShipmentStatus.CANCELLED}),
        ShipmentStatus.READY: frozenset({ShipmentStatus.ASSIGNED, ShipmentStatus.CANCELLED}),
        ShipmentStatus.ASSIGNED: frozenset(
            {ShipmentStatus.PICKED_UP, ShipmentStatus.CANCELLED, ShipmentStatus.FAILED}
        ),
        ShipmentStatus.PICKED_UP: frozenset(
            {
                ShipmentStatus.IN_TRANSIT,
                ShipmentStatus.CANCELLED,
                ShipmentStatus.FAILED,
            }
        ),
        ShipmentStatus.IN_TRANSIT: frozenset(
            {
                ShipmentStatus.DELAYED,
                ShipmentStatus.DELIVERED,
                ShipmentStatus.FAILED,
                ShipmentStatus.RETURNED,
                ShipmentStatus.CANCELLED,
            }
        ),
        ShipmentStatus.DELAYED: frozenset(
            {
                ShipmentStatus.IN_TRANSIT,
                ShipmentStatus.DELIVERED,
                ShipmentStatus.FAILED,
                ShipmentStatus.RETURNED,
                ShipmentStatus.CANCELLED,
            }
        ),
        # Failed permits a single follow-on return/compensation transition.
        ShipmentStatus.FAILED: frozenset({ShipmentStatus.RETURNED}),
        ShipmentStatus.DELIVERED: frozenset(),
        ShipmentStatus.CANCELLED: frozenset(),
        ShipmentStatus.RETURNED: frozenset(),
    }

    #: Terminal states from which no edit is permitted.
    TERMINAL_STATES: FrozenSet[ShipmentStatus] = frozenset(
        {
            ShipmentStatus.DELIVERED,
            ShipmentStatus.CANCELLED,
            ShipmentStatus.RETURNED,
            ShipmentStatus.FAILED,
        }
    )

    #: Committed states whose cancellation requires compensation.
    COMPENSATION_STATES: FrozenSet[ShipmentStatus] = frozenset(
        {
            ShipmentStatus.ASSIGNED,
            ShipmentStatus.PICKED_UP,
            ShipmentStatus.IN_TRANSIT,
            ShipmentStatus.DELAYED,
        }
    )

    #: States in which a driver+vehicle assignment is bound to the shipment.
    ASSIGNED_STATES: FrozenSet[ShipmentStatus] = frozenset(
        {
            ShipmentStatus.ASSIGNED,
            ShipmentStatus.PICKED_UP,
            ShipmentStatus.IN_TRANSIT,
            ShipmentStatus.DELAYED,
        }
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49
    )

    @classmethod
    def is_terminal(cls, status: ShipmentStatus) -> bool:
<<<<<<< HEAD
        """Return ``True`` if no transition/edit is allowed out of ``status``."""
=======
        """Return ``True`` if ``status`` is a terminal (non-editable) state."""
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: ShipmentStatus, target: ShipmentStatus) -> bool:
        """Return ``True`` if ``current → target`` is a permitted transition."""
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: ShipmentStatus, target: ShipmentStatus) -> None:
        """Raise :exc:`StatusTransitionError` if ``current → target`` is illegal."""
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition shipment from '{current.value}' to '{target.value}'."
            )

    @classmethod
<<<<<<< HEAD
    def can_cancel(cls, current: ShipmentStatus) -> bool:
        """Return ``True`` if a shipment in ``current`` may be cancelled."""
        return current in cls.CANCELLABLE_STATES

    @classmethod
=======
>>>>>>> f7f7b8d849bc2a1c28e9522e7d41b99bd920bb49
    def requires_compensation(cls, previous: ShipmentStatus) -> bool:
        """Return ``True`` if cancelling from ``previous`` needs compensation."""
        return previous in cls.COMPENSATION_STATES
