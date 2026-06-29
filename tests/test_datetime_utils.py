"""Unit tests for timezone-aware datetime utilities (app.common.datetime).

All functions in this module produce or consume UTC-aware datetimes. Tests
confirm:
* utcnow() always returns a timezone-aware datetime in UTC.
* to_epoch_ms() is correct for aware and naive inputs.
* from_epoch_ms() produces a UTC-aware datetime.
* The round-trip (utcnow → to_epoch_ms → from_epoch_ms) is lossless to the
  nearest millisecond.

No database or network access is required.
"""

from __future__ import annotations

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# utcnow
# ---------------------------------------------------------------------------


def test_utcnow_returns_datetime() -> None:
    from app.common.datetime import utcnow

    assert isinstance(utcnow(), datetime)


def test_utcnow_is_timezone_aware() -> None:
    from app.common.datetime import utcnow

    result = utcnow()
    assert result.tzinfo is not None, "utcnow() must return a timezone-aware datetime"


def test_utcnow_timezone_is_utc() -> None:
    from app.common.datetime import utcnow

    result = utcnow()
    assert result.tzinfo == timezone.utc


def test_utcnow_two_calls_are_non_decreasing() -> None:
    """Two successive calls must not go backwards in time."""
    from app.common.datetime import utcnow

    t1 = utcnow()
    t2 = utcnow()
    assert t2 >= t1


# ---------------------------------------------------------------------------
# to_epoch_ms
# ---------------------------------------------------------------------------


def test_to_epoch_ms_returns_int() -> None:
    from app.common.datetime import to_epoch_ms, utcnow

    assert isinstance(to_epoch_ms(utcnow()), int)


def test_to_epoch_ms_known_value() -> None:
    """1970-01-01T00:00:01Z should be exactly 1 000 ms."""
    from app.common.datetime import to_epoch_ms

    epoch_plus_one = datetime(1970, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    assert to_epoch_ms(epoch_plus_one) == 1_000


def test_to_epoch_ms_naive_assumed_utc() -> None:
    """Naive datetimes are treated as UTC rather than raising."""
    from app.common.datetime import to_epoch_ms

    naive = datetime(1970, 1, 1, 0, 0, 1)  # no tzinfo
    # Should not raise; result should match the aware equivalent.
    result = to_epoch_ms(naive)
    assert result == 1_000


def test_to_epoch_ms_millisecond_precision() -> None:
    """Millisecond sub-second component must be preserved."""
    from app.common.datetime import to_epoch_ms

    dt = datetime(2026, 1, 1, 12, 0, 0, 500_000, tzinfo=timezone.utc)  # 500 ms
    result = to_epoch_ms(dt)
    # The integer part must be a multiple of 1000, plus 500.
    assert result % 1_000 == 500


def test_to_epoch_ms_is_positive_for_recent_dates() -> None:
    from app.common.datetime import to_epoch_ms, utcnow

    assert to_epoch_ms(utcnow()) > 0


# ---------------------------------------------------------------------------
# from_epoch_ms
# ---------------------------------------------------------------------------


def test_from_epoch_ms_returns_datetime() -> None:
    from app.common.datetime import from_epoch_ms

    assert isinstance(from_epoch_ms(1_000), datetime)


def test_from_epoch_ms_is_timezone_aware() -> None:
    from app.common.datetime import from_epoch_ms

    result = from_epoch_ms(1_000)
    assert result.tzinfo is not None


def test_from_epoch_ms_timezone_is_utc() -> None:
    from app.common.datetime import from_epoch_ms

    result = from_epoch_ms(1_000)
    assert result.tzinfo == timezone.utc


def test_from_epoch_ms_zero_is_unix_epoch() -> None:
    from app.common.datetime import from_epoch_ms

    epoch = from_epoch_ms(0)
    assert epoch == datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_from_epoch_ms_one_second() -> None:
    from app.common.datetime import from_epoch_ms

    result = from_epoch_ms(1_000)
    assert result == datetime(1970, 1, 1, 0, 0, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip_aware_datetime_is_lossless_to_millisecond() -> None:
    """utcnow → to_epoch_ms → from_epoch_ms must be identical to the millisecond."""
    from app.common.datetime import from_epoch_ms, to_epoch_ms, utcnow

    original = utcnow()
    # Truncate to millisecond precision (Python datetimes have microsecond).
    ms = to_epoch_ms(original)
    restored = from_epoch_ms(ms)

    # The difference must be less than 1 millisecond.
    diff_us = abs((original - restored).total_seconds() * 1_000_000)
    assert diff_us < 1_000, f"Round-trip error {diff_us} µs exceeds 1 ms"


def test_round_trip_specific_timestamp() -> None:
    """A specific well-known timestamp survives the round-trip intact."""
    from app.common.datetime import from_epoch_ms, to_epoch_ms

    known = datetime(2026, 6, 1, 12, 30, 45, 123_000, tzinfo=timezone.utc)
    ms = to_epoch_ms(known)
    restored = from_epoch_ms(ms)
    assert restored == datetime(2026, 6, 1, 12, 30, 45, 123_000, tzinfo=timezone.utc)
