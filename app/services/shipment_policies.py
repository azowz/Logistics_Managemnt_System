"""Shipment domain policies — the lifecycle state machine (Sprint 5).

Separated from :class:`~app.services.shipment_service.ShipmentService` so the
transition rules are a single, testable source of truth (SRP), mirroring
:class:`~app.services.order_policies.OrderStateMachine`. The service delegates
every status change through :class:`ShipmentStateMachine`.

Lifecycle::

    created → ready → assigned → picked_up → in_transit → delivered
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
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.models.enums import ShipmentStatus
from app.services.exceptions import StatusTransitionError


class ShipmentStateMachine:
    """Validates and describes Shipment status transitions."""

    #: status → set of statuses reachable from it.
    ALLOWED_TRANSITIONS: Dict[ShipmentStatus, FrozenSet[ShipmentStatus]] = {
        ShipmentStatus.CREATED: frozenset(
            {ShipmentStatus.READY, ShipmentStatus.CANCELLED}
        ),
        ShipmentStatus.READY: frozenset(
            {ShipmentStatus.ASSIGNED, ShipmentStatus.CANCELLED}
        ),
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
    )

    @classmethod
    def is_terminal(cls, status: ShipmentStatus) -> bool:
        """Return ``True`` if ``status`` is a terminal (non-editable) state."""
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
    def requires_compensation(cls, previous: ShipmentStatus) -> bool:
        """Return ``True`` if cancelling from ``previous`` needs compensation."""
        return previous in cls.COMPENSATION_STATES
