"""RFC-9562 UUID version 7 generator (time-ordered, monotonic-safe).

UUIDv7 encodes a Unix millisecond timestamp in its most-significant 48 bits,
followed by 4 version bits, 12 bits of sub-millisecond / random data, the
2-bit variant, and 62 bits of randomness. The leading timestamp makes the
identifiers k-sortable, which is highly desirable for database primary keys
(index locality, range scans, natural insertion order).

This is a pure-Python implementation that:
  * sources wall-clock time from :func:`app.common.datetime.utcnow` so the
    whole application shares a single, testable time source;
  * uses ``os.urandom`` for the random bits;
  * guarantees strict monotonicity within a single process even when multiple
    identifiers are generated inside the same millisecond, by reusing the last
    timestamp and incrementing the random tail (Method 1 / "fixed bit-length
    dedicated counter" style guard from RFC-9562 §6.2).
"""

from __future__ import annotations

import os
import threading
import uuid

from app.common.datetime import to_epoch_ms, utcnow

# Bit layout constants (per RFC-9562 §5.7).
_VERSION = 0x7  # UUID version 7.
_VARIANT = 0b10  # RFC-4122 / RFC-9562 variant ("10xx").
_TIMESTAMP_BITS = 48
_RAND_A_BITS = 12  # Lower 12 bits of the time-high field (after the version).
_RAND_B_BITS = 62  # Tail randomness after the 2 variant bits.
_RAND_A_MASK = (1 << _RAND_A_BITS) - 1
_RAND_B_MASK = (1 << _RAND_B_BITS) - 1
_TOTAL_RAND_BITS = _RAND_A_BITS + _RAND_B_BITS  # 74 random/counter bits.
_TOTAL_RAND_MASK = (1 << _TOTAL_RAND_BITS) - 1

# Monotonicity guard state, protected by a lock so the generator is
# thread-safe under concurrent request handling.
_lock = threading.Lock()
_last_timestamp_ms: int = -1
_last_rand: int = 0


def _assemble(timestamp_ms: int, rand_bits: int) -> uuid.UUID:
    """Assemble a 128-bit UUIDv7 integer from a timestamp and random tail.

    ``rand_bits`` carries the combined ``rand_a`` (12 bits) and ``rand_b``
    (62 bits) payload; the version and variant nibbles are overlaid here so
    callers never have to reason about bit positions.
    """

    rand_a = (rand_bits >> _RAND_B_BITS) & _RAND_A_MASK
    rand_b = rand_bits & _RAND_B_MASK

    value = (timestamp_ms & ((1 << _TIMESTAMP_BITS) - 1)) << 80
    value |= _VERSION << 76
    value |= rand_a << 64
    value |= _VARIANT << 62
    value |= rand_b
    return uuid.UUID(int=value)


def uuid7() -> uuid.UUID:
    """Return a new, monotonically increasing RFC-9562 UUID version 7.

    The function is safe to call concurrently from multiple threads. Within a
    single millisecond it increments the previously emitted random tail to
    preserve strict ordering; if that 74-bit space were ever exhausted it
    advances the timestamp by one millisecond (an astronomically unlikely
    event in practice) so the result is always strictly greater than the prior
    one.
    """

    global _last_timestamp_ms, _last_rand

    timestamp_ms = to_epoch_ms(utcnow())

    with _lock:
        if timestamp_ms > _last_timestamp_ms:
            # Fresh millisecond: draw a brand-new random tail.
            rand_bits = int.from_bytes(os.urandom(10), "big") & _TOTAL_RAND_MASK
            _last_timestamp_ms = timestamp_ms
            _last_rand = rand_bits
        else:
            # Same (or backwards) clock reading: keep ordering by incrementing.
            timestamp_ms = _last_timestamp_ms
            rand_bits = (_last_rand + 1) & _TOTAL_RAND_MASK
            if rand_bits == 0:
                # Counter overflow within a millisecond; bump time forward.
                timestamp_ms += 1
                _last_timestamp_ms = timestamp_ms
                rand_bits = int.from_bytes(os.urandom(10), "big") & _TOTAL_RAND_MASK
            _last_rand = rand_bits

        return _assemble(timestamp_ms, rand_bits)


__all__ = ["uuid7"]
