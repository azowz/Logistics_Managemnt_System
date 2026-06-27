"""Exception hierarchy for the event backbone."""

from __future__ import annotations


class EventBackboneError(Exception):
    """Base class for all event-backbone errors."""


class UnknownEventTypeError(EventBackboneError):
    """Raised when an event type/version has no registered class to deserialize into."""


class EventDeserializationError(EventBackboneError):
    """Raised when a stored payload cannot be reconstructed into a domain event."""


class ConcurrencyConflictError(EventBackboneError):
    """Raised when appending an event violates ``(aggregate_id, aggregate_version)``.

    This is the optimistic-concurrency signal: a competing writer already wrote
    the same next version for the aggregate. The caller should reload and retry.
    """


class EventPublishError(EventBackboneError):
    """Raised when the bus fails to publish an envelope (relay records + retries)."""


__all__ = [
    "EventBackboneError",
    "UnknownEventTypeError",
    "EventDeserializationError",
    "ConcurrencyConflictError",
    "EventPublishError",
]
