"""Timezone-aware datetime helpers.

Every timestamp produced by the Mesaar backend MUST be timezone-aware and
expressed in UTC. These helpers centralize that contract so callers never have
to reach for ``datetime.utcnow()`` (which returns a naive value) directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["utcnow", "to_epoch_ms", "from_epoch_ms"]


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC :class:`datetime`.

    Returns:
        A ``datetime`` whose ``tzinfo`` is :data:`datetime.timezone.utc`.
    """

    return datetime.now(timezone.utc)


def to_epoch_ms(dt: datetime) -> int:
    """Convert a :class:`datetime` to integer milliseconds since the Unix epoch.

    Naive datetimes are assumed to be UTC (rather than raising), which keeps the
    helper forgiving at serialization boundaries while still being explicit
    about the assumption.

    Args:
        dt: The datetime to convert.

    Returns:
        Whole milliseconds since ``1970-01-01T00:00:00Z``.
    """

    if dt.tzinfo is None:
        # Assume UTC for naive inputs rather than letting Python apply the
        # local timezone, which would silently corrupt the value.
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def from_epoch_ms(epoch_ms: int) -> datetime:
    """Build a timezone-aware UTC :class:`datetime` from epoch milliseconds.

    Args:
        epoch_ms: Milliseconds since ``1970-01-01T00:00:00Z``.

    Returns:
        The corresponding timezone-aware UTC datetime.
    """

    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
