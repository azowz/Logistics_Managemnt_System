"""Domain-specific exceptions raised by service layer logic."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for domain errors."""


class ValidationError(DomainError):
    """Raised when input data violates domain rules."""


class NotFoundError(DomainError):
    """Raised when a required entity cannot be located."""


class ConflictError(DomainError):
    """Raised when an operation conflicts with existing state (e.g. duplicate key)."""


class CapacityError(DomainError):
    """Raised when warehouse capacity constraints would be exceeded."""


class AssignmentError(DomainError):
    """Raised when shipment assignment rules are violated."""


class StatusTransitionError(DomainError):
    """Raised when an invalid status transition is attempted."""


class TrackingEventError(DomainError):
    """Raised when tracking event creation is invalid."""
