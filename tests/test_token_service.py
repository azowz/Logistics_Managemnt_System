"""Unit tests for app.core.token_service.TokenService.

All tests use a MagicMock for the Redis client — no live Redis required.
Covers: issue, consume, revoke, denylist, denylist-check.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.token_service import TokenService, _DENYLIST_PREFIX, _REFRESH_PREFIX


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_redis() -> MagicMock:
    """A fully mocked Redis client."""
    return MagicMock()


@pytest.fixture()
def svc(mock_redis: MagicMock) -> TokenService:
    """TokenService wired to the mock Redis client."""
    return TokenService(mock_redis)


# ---------------------------------------------------------------------------
# issue_refresh_token
# ---------------------------------------------------------------------------


def test_issue_refresh_token_returns_non_empty_string(svc: TokenService) -> None:
    token = svc.issue_refresh_token(user_id="u1", tenant_id="t1", role="admin")
    assert isinstance(token, str) and token


def test_issue_refresh_token_calls_setex(svc: TokenService, mock_redis: MagicMock) -> None:
    token = svc.issue_refresh_token(user_id="u1", tenant_id="t1", role="admin")
    mock_redis.setex.assert_called_once()
    key, ttl, payload = mock_redis.setex.call_args.args
    assert key == f"{_REFRESH_PREFIX}:{token}"
    assert ttl > 0
    data = json.loads(payload)
    assert data["user_id"] == "u1"
    assert data["tenant_id"] == "t1"
    assert data["role"] == "admin"


def test_issue_refresh_token_ttl_matches_settings(svc: TokenService, mock_redis: MagicMock) -> None:
    from app.core.config import get_settings

    svc.issue_refresh_token(user_id="u1", tenant_id="t1", role="admin")
    _, ttl, _ = mock_redis.setex.call_args.args
    expected_ttl = get_settings().refresh_token_expire_minutes * 60
    assert ttl == expected_ttl


def test_issue_refresh_token_each_call_unique(svc: TokenService) -> None:
    t1 = svc.issue_refresh_token(user_id="u", tenant_id="t", role="admin")
    t2 = svc.issue_refresh_token(user_id="u", tenant_id="t", role="admin")
    assert t1 != t2


# ---------------------------------------------------------------------------
# consume_refresh_token
# ---------------------------------------------------------------------------


def test_consume_returns_payload_on_valid_token(svc: TokenService, mock_redis: MagicMock) -> None:
    payload = {"user_id": "u1", "tenant_id": "t1", "role": "admin"}
    mock_redis.getdel.return_value = json.dumps(payload).encode()

    result = svc.consume_refresh_token("some-token")

    assert result == payload


def test_consume_calls_getdel_with_correct_key(svc: TokenService, mock_redis: MagicMock) -> None:
    mock_redis.getdel.return_value = json.dumps({"user_id": "x", "tenant_id": "y", "role": "r"}).encode()

    svc.consume_refresh_token("my-token")

    mock_redis.getdel.assert_called_once_with(f"{_REFRESH_PREFIX}:my-token")


def test_consume_returns_none_for_missing_token(svc: TokenService, mock_redis: MagicMock) -> None:
    mock_redis.getdel.return_value = None
    assert svc.consume_refresh_token("nonexistent") is None


def test_consume_deletes_key_atomically(svc: TokenService, mock_redis: MagicMock) -> None:
    """GETDEL must be called — not separate GET + DELETE — to prevent replay."""
    mock_redis.getdel.return_value = None
    svc.consume_refresh_token("t")
    mock_redis.get.assert_not_called()
    mock_redis.delete.assert_not_called()
    mock_redis.getdel.assert_called_once()


# ---------------------------------------------------------------------------
# revoke_refresh_token
# ---------------------------------------------------------------------------


def test_revoke_calls_delete_with_correct_key(svc: TokenService, mock_redis: MagicMock) -> None:
    svc.revoke_refresh_token("some-token")
    mock_redis.delete.assert_called_once_with(f"{_REFRESH_PREFIX}:some-token")


def test_revoke_does_not_call_getdel(svc: TokenService, mock_redis: MagicMock) -> None:
    svc.revoke_refresh_token("t")
    mock_redis.getdel.assert_not_called()


# ---------------------------------------------------------------------------
# denylist_access_token
# ---------------------------------------------------------------------------


def test_denylist_calls_setex_with_correct_key(svc: TokenService, mock_redis: MagicMock) -> None:
    svc.denylist_access_token("jti-123", ttl_seconds=600)
    mock_redis.setex.assert_called_once_with(f"{_DENYLIST_PREFIX}:jti-123", 600, "1")


def test_denylist_zero_ttl_is_noop(svc: TokenService, mock_redis: MagicMock) -> None:
    svc.denylist_access_token("jti-123", ttl_seconds=0)
    mock_redis.setex.assert_not_called()


def test_denylist_negative_ttl_is_noop(svc: TokenService, mock_redis: MagicMock) -> None:
    svc.denylist_access_token("jti-123", ttl_seconds=-10)
    mock_redis.setex.assert_not_called()


def test_denylist_positive_ttl_calls_setex(svc: TokenService, mock_redis: MagicMock) -> None:
    svc.denylist_access_token("j1", ttl_seconds=1)
    mock_redis.setex.assert_called_once()


# ---------------------------------------------------------------------------
# is_denylisted
# ---------------------------------------------------------------------------


def test_is_denylisted_true_when_key_exists(svc: TokenService, mock_redis: MagicMock) -> None:
    mock_redis.exists.return_value = 1
    assert svc.is_denylisted("jti-abc") is True
    mock_redis.exists.assert_called_once_with(f"{_DENYLIST_PREFIX}:jti-abc")


def test_is_denylisted_false_when_key_absent(svc: TokenService, mock_redis: MagicMock) -> None:
    mock_redis.exists.return_value = 0
    assert svc.is_denylisted("jti-abc") is False


def test_is_denylisted_returns_bool(svc: TokenService, mock_redis: MagicMock) -> None:
    mock_redis.exists.return_value = 1
    result = svc.is_denylisted("x")
    assert isinstance(result, bool)
