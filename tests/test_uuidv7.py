"""Unit tests for the RFC-9562 UUIDv7 generator (app.db.uuidv7).

Tests cover:
* Structural correctness (version nibble = 7, correct variant bits).
* Monotonicity — successive calls always produce a strictly increasing integer.
* Uniqueness — no duplicates across a large sample.
* Thread-safety — concurrent generation produces all-unique values with no
  monotonicity violation.

No database or network access is required.
"""

from __future__ import annotations

import threading
import uuid

import pytest

from app.db.uuidv7 import uuid7


# ---------------------------------------------------------------------------
# Structural / format tests
# ---------------------------------------------------------------------------


def test_uuid7_returns_uuid_instance() -> None:
    assert isinstance(uuid7(), uuid.UUID)


def test_uuid7_version_nibble_is_7() -> None:
    """The version nibble (bits 76-79) must equal 7 per RFC-9562 §5.7."""
    result = uuid7()
    version_nibble = (result.int >> 76) & 0xF
    assert version_nibble == 7, f"Expected version 7, got {version_nibble}"


def test_uuid7_variant_bits_are_rfc4122() -> None:
    """Variant bits 62-63 must be 0b10 (RFC-4122 variant)."""
    result = uuid7()
    variant_bits = (result.int >> 62) & 0b11
    assert variant_bits == 0b10, f"Expected RFC-4122 variant (0b10), got {variant_bits:#04b}"


def test_uuid7_has_correct_string_length() -> None:
    """UUID v7 string representation must be 36 chars (8-4-4-4-12)."""
    result = str(uuid7())
    assert len(result) == 36
    assert result.count("-") == 4


def test_uuid7_version_field_matches_uuid_library() -> None:
    """uuid.UUID.version should report 7 for a well-formed UUIDv7."""
    result = uuid7()
    assert result.version == 7


# ---------------------------------------------------------------------------
# Monotonicity
# ---------------------------------------------------------------------------


def test_uuid7_successive_calls_are_monotonically_increasing() -> None:
    """100 consecutive calls must produce strictly increasing integer values."""
    ids = [uuid7() for _ in range(100)]
    for i in range(1, len(ids)):
        assert ids[i].int > ids[i - 1].int, (
            f"Monotonicity violated at index {i}: "
            f"{ids[i].int} <= {ids[i-1].int}"
        )


def test_uuid7_large_batch_is_monotonic() -> None:
    """1 000 calls in tight succession must all be strictly increasing."""
    ids = [uuid7() for _ in range(1_000)]
    ints = [u.int for u in ids]
    assert ints == sorted(ints), "UUIDv7 batch is not monotonically increasing"


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------


def test_uuid7_no_duplicates_in_1000() -> None:
    ids = [uuid7() for _ in range(1_000)]
    assert len(set(ids)) == 1_000, "Duplicate UUIDv7 values detected"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def _worker(count: int, results: list[uuid.UUID]) -> None:
    """Generate ``count`` UUIDs and append them to the shared list."""
    for _ in range(count):
        results.append(uuid7())


def test_uuid7_thread_safe_all_unique() -> None:
    """10 threads × 200 calls = 2 000 UUIDs; all must be unique."""
    n_threads, n_per_thread = 10, 200
    results: list[uuid.UUID] = []
    lock = threading.Lock()

    def _safe_worker():
        local = [uuid7() for _ in range(n_per_thread)]
        with lock:
            results.extend(local)

    threads = [threading.Thread(target=_safe_worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = n_threads * n_per_thread
    assert len(results) == total
    assert len(set(results)) == total, "Thread-safe uniqueness violated"


def test_uuid7_thread_safe_monotonic_per_thread() -> None:
    """Each thread's own sequence must be monotonically increasing."""
    n_per_thread = 200
    per_thread: list[list[uuid.UUID]] = []
    lock = threading.Lock()

    def _worker():
        local = [uuid7() for _ in range(n_per_thread)]
        with lock:
            per_thread.append(local)

    threads = [threading.Thread(target=_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for seq in per_thread:
        ints = [u.int for u in seq]
        assert ints == sorted(ints), "Per-thread sequence is not monotonic"


# ---------------------------------------------------------------------------
# Timestamp encoding
# ---------------------------------------------------------------------------


def test_uuid7_timestamp_is_recent() -> None:
    """The 48-bit timestamp field should reflect a recent Unix timestamp (ms)."""
    import time

    before_ms = int(time.time() * 1000)
    u = uuid7()
    after_ms = int(time.time() * 1000)

    # Top 48 bits of the UUID integer carry the millisecond timestamp.
    encoded_ms = u.int >> 80

    assert before_ms <= encoded_ms <= after_ms + 1, (
        f"UUID timestamp {encoded_ms} is outside expected window "
        f"[{before_ms}, {after_ms}]"
    )
