"""Compliance domain policies — the Permit lifecycle state machine (Sprint 7).

Single source of truth for permit transitions, mirroring the Order/Shipment/
Equipment state machines. The service delegates every status change here.

Lifecycle::

    draft → submitted → under_review → approved → active → expired
      │         │            │            │          │
      └─────────┴────────────┴────────────┴──────────┴──→ cancelled
                             └──→ rejected

Terminal: ``rejected``, ``expired``, ``cancelled``.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.models.enums import PermitStatus
from app.services.exceptions import StatusTransitionError


class PermitStateMachine:
    """Validates and describes Permit status transitions."""

    ALLOWED_TRANSITIONS: Dict[PermitStatus, FrozenSet[PermitStatus]] = {
        PermitStatus.DRAFT: frozenset({PermitStatus.SUBMITTED, PermitStatus.CANCELLED}),
        PermitStatus.SUBMITTED: frozenset({PermitStatus.UNDER_REVIEW, PermitStatus.CANCELLED}),
        PermitStatus.UNDER_REVIEW: frozenset(
            {PermitStatus.APPROVED, PermitStatus.REJECTED, PermitStatus.CANCELLED}
        ),
        PermitStatus.APPROVED: frozenset({PermitStatus.ACTIVE, PermitStatus.CANCELLED}),
        PermitStatus.ACTIVE: frozenset({PermitStatus.EXPIRED, PermitStatus.CANCELLED}),
        PermitStatus.REJECTED: frozenset(),
        PermitStatus.EXPIRED: frozenset(),
        PermitStatus.CANCELLED: frozenset(),
    }

    TERMINAL_STATES: FrozenSet[PermitStatus] = frozenset(
        {PermitStatus.REJECTED, PermitStatus.EXPIRED, PermitStatus.CANCELLED}
    )

    #: Statuses in which a permit authorizes dispatch.
    DISPATCHABLE_STATES: FrozenSet[PermitStatus] = frozenset({PermitStatus.ACTIVE})

    @classmethod
    def is_terminal(cls, status: PermitStatus) -> bool:
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: PermitStatus, target: PermitStatus) -> bool:
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: PermitStatus, target: PermitStatus) -> None:
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition permit from '{current.value}' to '{target.value}'."
            )

    @classmethod
    def is_dispatchable(cls, status: PermitStatus) -> bool:
        """Return ``True`` if a permit in ``status`` authorizes a movement."""
        return status in cls.DISPATCHABLE_STATES
