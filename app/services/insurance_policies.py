"""Insurance & Claims domain policies — Policy and Claim state machines (Sprint 8).

Single source of truth for transitions, mirroring the other domains. Services
delegate every status change here.

Policy::
    draft → active → {suspended, expired, cancelled}
    suspended → {active, expired, cancelled}
  Terminal: expired, cancelled.

Claim::
    created → under_review → {approved, rejected}
    approved → settled → closed
    rejected → closed
    closed → under_review  (explicit reopen)
  Terminal: closed (reopenable).
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.models.enums import ClaimStatus, InsurancePolicyStatus
from app.services.exceptions import StatusTransitionError


class PolicyStateMachine:
    """Validates and describes InsurancePolicy status transitions."""

    ALLOWED_TRANSITIONS: Dict[InsurancePolicyStatus, FrozenSet[InsurancePolicyStatus]] = {
        InsurancePolicyStatus.DRAFT: frozenset(
            {InsurancePolicyStatus.ACTIVE, InsurancePolicyStatus.CANCELLED}
        ),
        InsurancePolicyStatus.ACTIVE: frozenset(
            {
                InsurancePolicyStatus.SUSPENDED,
                InsurancePolicyStatus.EXPIRED,
                InsurancePolicyStatus.CANCELLED,
            }
        ),
        InsurancePolicyStatus.SUSPENDED: frozenset(
            {
                InsurancePolicyStatus.ACTIVE,
                InsurancePolicyStatus.EXPIRED,
                InsurancePolicyStatus.CANCELLED,
            }
        ),
        InsurancePolicyStatus.EXPIRED: frozenset(),
        InsurancePolicyStatus.CANCELLED: frozenset(),
    }

    TERMINAL_STATES: FrozenSet[InsurancePolicyStatus] = frozenset(
        {InsurancePolicyStatus.EXPIRED, InsurancePolicyStatus.CANCELLED}
    )

    @classmethod
    def is_terminal(cls, status: InsurancePolicyStatus) -> bool:
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current, target) -> bool:
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current, target) -> None:
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition policy from '{current.value}' to '{target.value}'."
            )

    @classmethod
    def can_cover(cls, status: InsurancePolicyStatus) -> bool:
        """Return ``True`` if a policy in ``status`` can back a claim approval."""
        return status == InsurancePolicyStatus.ACTIVE


class ClaimStateMachine:
    """Validates and describes Claim status transitions."""

    ALLOWED_TRANSITIONS: Dict[ClaimStatus, FrozenSet[ClaimStatus]] = {
        ClaimStatus.CREATED: frozenset({ClaimStatus.UNDER_REVIEW}),
        ClaimStatus.UNDER_REVIEW: frozenset(
            {ClaimStatus.APPROVED, ClaimStatus.REJECTED}
        ),
        ClaimStatus.APPROVED: frozenset({ClaimStatus.SETTLED}),
        ClaimStatus.SETTLED: frozenset({ClaimStatus.CLOSED}),
        ClaimStatus.REJECTED: frozenset({ClaimStatus.CLOSED}),
        # closed is terminal but may be explicitly reopened to under_review.
        ClaimStatus.CLOSED: frozenset({ClaimStatus.UNDER_REVIEW}),
    }

    #: closed is the natural terminal (reopen is an explicit exception).
    TERMINAL_STATES: FrozenSet[ClaimStatus] = frozenset({ClaimStatus.CLOSED})

    @classmethod
    def is_terminal(cls, status: ClaimStatus) -> bool:
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: ClaimStatus, target: ClaimStatus) -> bool:
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: ClaimStatus, target: ClaimStatus) -> None:
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition claim from '{current.value}' to '{target.value}'."
            )
