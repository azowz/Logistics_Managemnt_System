"""Order domain policies — the lifecycle state machine.

Separated from :class:`~app.services.order_service.OrderService` so the
transition rules are a single, testable source of truth (SRP). The service
delegates every status change through :class:`OrderStateMachine`.

Lifecycle::

    draft → submitted → approved → scheduled → assigned → in_transit → delivered
              │            │           │           │            │
              └────────────┴───────────┴───────────┴────────────┴──→ cancelled
                           └───────────┴───────────┴────────────┴──→ failed

``delivered``, ``cancelled`` and ``failed`` are terminal.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.models.enums import OrderStatus
from app.services.exceptions import StatusTransitionError


class OrderStateMachine:
    """Validates and describes Order status transitions."""

    #: status → set of statuses reachable from it.
    ALLOWED_TRANSITIONS: Dict[OrderStatus, FrozenSet[OrderStatus]] = {
        OrderStatus.DRAFT: frozenset({OrderStatus.SUBMITTED, OrderStatus.CANCELLED}),
        OrderStatus.SUBMITTED: frozenset(
            {OrderStatus.APPROVED, OrderStatus.CANCELLED, OrderStatus.FAILED}
        ),
        OrderStatus.APPROVED: frozenset(
            {OrderStatus.SCHEDULED, OrderStatus.CANCELLED, OrderStatus.FAILED}
        ),
        OrderStatus.SCHEDULED: frozenset(
            {OrderStatus.ASSIGNED, OrderStatus.CANCELLED, OrderStatus.FAILED}
        ),
        OrderStatus.ASSIGNED: frozenset(
            {OrderStatus.IN_TRANSIT, OrderStatus.CANCELLED, OrderStatus.FAILED}
        ),
        OrderStatus.IN_TRANSIT: frozenset(
            {OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.FAILED}
        ),
        OrderStatus.DELIVERED: frozenset(),
        OrderStatus.CANCELLED: frozenset(),
        OrderStatus.FAILED: frozenset(),
    }

    #: Terminal states no further transition is permitted from.
    TERMINAL_STATES: FrozenSet[OrderStatus] = frozenset(
        {OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.FAILED}
    )

    #: In-progress states whose cancellation requires compensation.
    COMPENSATION_STATES: FrozenSet[OrderStatus] = frozenset(
        {OrderStatus.ASSIGNED, OrderStatus.IN_TRANSIT}
    )

    @classmethod
    def is_terminal(cls, status: OrderStatus) -> bool:
        """Return ``True`` if no transition is allowed out of ``status``."""
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: OrderStatus, target: OrderStatus) -> bool:
        """Return ``True`` if ``current → target`` is a permitted transition."""
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: OrderStatus, target: OrderStatus) -> None:
        """Raise :exc:`StatusTransitionError` if ``current → target`` is illegal."""
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition order from '{current.value}' to '{target.value}'."
            )

    @classmethod
    def requires_compensation(cls, previous: OrderStatus) -> bool:
        """Return ``True`` if cancelling from ``previous`` needs compensation."""
        return previous in cls.COMPENSATION_STATES
