"""Sprint 14 hardening unit tests: scopes/IP validation, Redis backend, backoff (no DB)."""

from __future__ import annotations

import pytest

from app.integrations.policies import (
    RateLimitPolicy,
    RedisRateLimitBackend,
    SCOPE_INBOUND_WRITE,
    ip_allowed,
    validate_allowed_ips,
    validate_scopes,
)
from app.services.exceptions import ValidationError
from app.services.integration_service import _retry_backoff_seconds


# --- scope validation ---


def test_validate_scopes_known_and_dedup():
    assert validate_scopes([SCOPE_INBOUND_WRITE, SCOPE_INBOUND_WRITE]) == [SCOPE_INBOUND_WRITE]
    assert validate_scopes(None) is None
    assert validate_scopes([]) is None
    with pytest.raises(ValidationError):
        validate_scopes(["integrations:unknown"])


# --- allowed-IP validation + matching ---


def test_validate_allowed_ips_and_matching():
    assert validate_allowed_ips(None) is None
    assert validate_allowed_ips([]) is None
    assert validate_allowed_ips(["10.0.0.1", "192.168.0.0/24"]) == ["10.0.0.1", "192.168.0.0/24"]
    with pytest.raises(ValidationError):
        validate_allowed_ips(["not-an-ip"])
    with pytest.raises(ValidationError):
        validate_allowed_ips("10.0.0.1")  # not a list

    assert ip_allowed("1.2.3.4", None) is True          # empty → allow any
    assert ip_allowed("10.0.0.1", ["10.0.0.1"]) is True  # exact
    assert ip_allowed("192.168.0.9", ["192.168.0.0/24"]) is True  # CIDR
    assert ip_allowed("10.0.0.9", ["192.168.0.0/24"]) is False    # outside CIDR
    assert ip_allowed(None, ["10.0.0.1"]) is False        # no client IP but restricted
    assert ip_allowed("garbage", ["10.0.0.1"]) is False   # unparseable client IP


# --- backoff ---


def test_retry_backoff_is_bounded_exponential():
    seq = [_retry_backoff_seconds(n) for n in range(1, 9)]
    assert seq[:4] == [30, 60, 120, 240]
    assert all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1))  # monotonic
    assert max(seq) <= 3600  # capped


# --- Redis rate-limit backend (fake client) ---


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.expires = {}

    def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key, ttl):
        self.expires[key] = ttl


class _BoomRedis:
    def incr(self, key):
        raise RuntimeError("redis down")

    def expire(self, key, ttl):
        pass


def test_redis_backend_counts_and_limits():
    backend = RedisRateLimitBackend(client=_FakeRedis(), window_seconds=60)
    rl = RateLimitPolicy(limit=2, window_seconds=60, backend=backend)
    d = [rl.check("t:k", now=1000.0 + i) for i in range(3)]
    assert d[0].allowed and d[1].allowed and not d[2].allowed
    # a different key is independent
    assert rl.check("t:other", now=1000.0).allowed


def test_redis_backend_fails_open_by_default():
    backend = RedisRateLimitBackend(client=_BoomRedis(), window_seconds=60)
    # incr returns 0 on error → treated as under-limit (fail open)
    assert backend.incr("k", 1) == 0
    rl = RateLimitPolicy(limit=1, window_seconds=60, backend=backend)
    assert rl.check("t:k", now=1.0).allowed  # never blocks on Redis outage


def test_redis_backend_can_fail_closed():
    backend = RedisRateLimitBackend(client=_BoomRedis(), window_seconds=60, fail_open=False)
    assert backend.incr("k", 1) > 1_000  # over any limit → deny
    rl = RateLimitPolicy(limit=100, window_seconds=60, backend=backend)
    assert not rl.check("t:k", now=1.0).allowed


def test_redis_backend_uses_get_redis_when_no_client(monkeypatch):
    """The default (no injected client) path resolves app.core.redis.get_redis."""
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake)
    backend = RedisRateLimitBackend(window_seconds=60)  # no client → get_redis()
    assert backend.incr("t:k", 1) == 1
    assert backend.incr("t:k", 1) == 2
    assert fake.expires  # expire set on first incr
