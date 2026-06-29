"""Unit tests for application configuration (app.core.config).

These tests exercise Settings validation, the CORS-origins preprocessor, the
is_production property, and the lru_cache singleton behaviour — all without
touching the database, Redis, or any external service.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    """Return a fresh Settings instance, bypassing the lru_cache."""
    from app.core.config import Settings

    return Settings(**overrides)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_default_database_url_contains_postgres() -> None:
    s = _make_settings()
    assert "postgres" in s.database_url or "sqlite" in s.database_url


def test_default_environment_is_development() -> None:
    s = _make_settings()
    assert s.environment in {"development", "test"}  # test env set by conftest


def test_default_app_name_is_set() -> None:
    s = _make_settings()
    assert s.app_name  # non-empty


def test_default_log_level_is_info() -> None:
    s = _make_settings()
    assert s.log_level == "INFO"


def test_default_access_token_expire_minutes() -> None:
    s = _make_settings()
    assert s.access_token_expire_minutes == 60


def test_default_bcrypt_work_factor() -> None:
    s = _make_settings()
    assert 8 <= s.bcrypt_work_factor <= 16


def test_default_db_pool_size() -> None:
    s = _make_settings()
    assert s.db_pool_size >= 1


def test_default_refresh_token_expire_minutes() -> None:
    s = _make_settings()
    # Default is 14 days.
    assert s.refresh_token_expire_minutes == 60 * 24 * 14


def test_default_jwt_issuer() -> None:
    s = _make_settings()
    assert s.jwt_issuer == "mesaar"


def test_default_jwt_audience() -> None:
    s = _make_settings()
    assert s.jwt_audience == "mesaar-clients"


# ---------------------------------------------------------------------------
# is_production property
# ---------------------------------------------------------------------------


def test_is_production_true_when_environment_is_production() -> None:
    s = _make_settings(environment="production")
    assert s.is_production is True


def test_is_production_false_when_development() -> None:
    s = _make_settings(environment="development")
    assert s.is_production is False


def test_is_production_false_when_staging() -> None:
    s = _make_settings(environment="staging")
    assert s.is_production is False


def test_is_production_false_when_test() -> None:
    s = _make_settings(environment="test")
    assert s.is_production is False


# ---------------------------------------------------------------------------
# Secret key validation
# ---------------------------------------------------------------------------


def test_secret_key_minimum_length_enforced() -> None:
    """Secret key shorter than 32 characters must be rejected."""
    with pytest.raises((PydanticValidationError, ValueError)):
        _make_settings(secret_key="short")


def test_secret_key_exactly_32_chars_accepted() -> None:
    s = _make_settings(secret_key="a" * 32)
    assert len(s.secret_key) == 32


# ---------------------------------------------------------------------------
# CORS origins validator
# ---------------------------------------------------------------------------


def test_cors_origins_list_passthrough() -> None:
    origins = ["https://a.example.com", "https://b.example.com"]
    s = _make_settings(cors_origins=origins)
    assert s.cors_origins == origins


def test_cors_origins_comma_string_is_split() -> None:
    s = _make_settings(cors_origins="https://a.example.com,https://b.example.com")
    assert s.cors_origins == ["https://a.example.com", "https://b.example.com"]


def test_cors_origins_comma_string_strips_whitespace() -> None:
    s = _make_settings(cors_origins=" https://a.example.com , https://b.example.com ")
    assert s.cors_origins == ["https://a.example.com", "https://b.example.com"]


def test_cors_origins_empty_string_yields_empty_list() -> None:
    s = _make_settings(cors_origins="")
    assert s.cors_origins == []


def test_cors_origins_whitespace_only_yields_empty_list() -> None:
    s = _make_settings(cors_origins="   ")
    assert s.cors_origins == []


def test_cors_origins_single_value_string() -> None:
    s = _make_settings(cors_origins="https://app.example.com")
    assert s.cors_origins == ["https://app.example.com"]


# ---------------------------------------------------------------------------
# Bounded fields
# ---------------------------------------------------------------------------


def test_bcrypt_work_factor_lower_bound_8() -> None:
    with pytest.raises((PydanticValidationError, ValueError)):
        _make_settings(bcrypt_work_factor=7)


def test_bcrypt_work_factor_upper_bound_16() -> None:
    with pytest.raises((PydanticValidationError, ValueError)):
        _make_settings(bcrypt_work_factor=17)


def test_access_token_lower_bound_5_minutes() -> None:
    with pytest.raises((PydanticValidationError, ValueError)):
        _make_settings(access_token_expire_minutes=4)


def test_db_pool_size_must_be_at_least_1() -> None:
    with pytest.raises((PydanticValidationError, ValueError)):
        _make_settings(db_pool_size=0)


# ---------------------------------------------------------------------------
# Singleton via get_settings
# ---------------------------------------------------------------------------


def test_get_settings_returns_same_instance_twice() -> None:
    from app.core.config import get_settings

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_get_settings_returns_settings_type() -> None:
    from app.core.config import Settings, get_settings

    assert isinstance(get_settings(), Settings)
