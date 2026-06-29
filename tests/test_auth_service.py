"""Unit tests for app.services.auth_service.AuthService.

All external dependencies (UserRepository, TenantRepository, TokenService,
Redis) are mocked via unittest.mock — no database or Redis required.
"""

from __future__ import annotations

import time
import uuid
from datetime import timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import UserRole
from app.services.exceptions import ConflictError, ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    *,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    email: str = "alice@example.com",
    role: UserRole = UserRole.ADMIN,
    is_active: bool = True,
) -> MagicMock:
    """Return a mock User with the given attributes.

    ``role`` is set to the actual :class:`UserRole` enum instance so that
    ``user.role.value`` works naturally without trying to mutate the enum.
    """
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.tenant_id = tenant_id or uuid.uuid4()
    u.email = email
    # Assign the real enum so u.role.value returns the correct string.
    u.role = role
    u.is_active = is_active
    u.hashed_password = "hashed"
    return u


def _make_auth_service(
    *,
    user: MagicMock | None = None,
    tenant: MagicMock | None = None,
    slug_taken: bool = False,
):
    """Build an AuthService with fully mocked dependencies."""
    from app.services.auth_service import AuthService

    mock_session = MagicMock()
    mock_redis = MagicMock()
    mock_redis.getdel.return_value = None
    mock_redis.exists.return_value = 0

    svc = AuthService(mock_session, redis=mock_redis)

    # Patch repos directly on the instance.
    svc._user_repo = MagicMock()
    svc._tenant_repo = MagicMock()
    svc._token_service = MagicMock()
    svc._token_service.issue_refresh_token.return_value = "refresh-tok"
    svc._token_service.consume_refresh_token.return_value = None
    svc._token_service.is_denylisted.return_value = False

    if user is not None:
        svc._user_repo.get_by_email.return_value = user
        svc._user_repo.get_by_id.return_value = user
        svc._user_repo.create.return_value = user
    else:
        svc._user_repo.get_by_email.return_value = None
        svc._user_repo.get_by_id.return_value = None

    if tenant is not None:
        svc._tenant_repo.get_by_slug.return_value = tenant if slug_taken else None
        svc._tenant_repo.add.return_value = tenant
    else:
        svc._tenant_repo.get_by_slug.return_value = None
        svc._tenant_repo.add.return_value = MagicMock(id=uuid.uuid4())

    return svc


# ---------------------------------------------------------------------------
# authenticate()
# ---------------------------------------------------------------------------


def test_authenticate_returns_user_on_valid_creds() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)

    with patch("app.services.auth_service.security.verify_password", return_value=True):
        result = svc.authenticate("alice@example.com", "password1")

    assert result is user


def test_authenticate_returns_none_on_wrong_password() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)

    with patch("app.services.auth_service.security.verify_password", return_value=False):
        result = svc.authenticate("alice@example.com", "wrong")

    assert result is None


def test_authenticate_returns_none_when_user_not_found() -> None:
    svc = _make_auth_service(user=None)
    result = svc.authenticate("nobody@example.com", "pass1234")
    assert result is None


def test_authenticate_returns_none_for_inactive_user() -> None:
    user = _make_user(is_active=False)
    svc = _make_auth_service(user=user)

    with patch("app.services.auth_service.security.verify_password", return_value=True):
        result = svc.authenticate("alice@example.com", "pass1234")

    assert result is None


def test_authenticate_passes_tenant_id_to_repo() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)
    tid = uuid.uuid4()

    with patch("app.services.auth_service.security.verify_password", return_value=True):
        svc.authenticate("alice@example.com", "pass1234", tenant_id=tid)

    svc._user_repo.get_by_email.assert_called_once_with(
        email="alice@example.com", tenant_id=tid
    )


# ---------------------------------------------------------------------------
# issue_token_pair()
# ---------------------------------------------------------------------------


def test_issue_token_pair_returns_two_non_empty_strings() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)

    with patch("app.services.auth_service.security.create_access_token", return_value="access-tok"):
        access, refresh = svc.issue_token_pair(user)

    assert access == "access-tok"
    assert refresh == "refresh-tok"


def test_issue_token_pair_calls_create_access_token_with_jti() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)

    with patch("app.services.auth_service.security.create_access_token", return_value="tok") as mock_cat:
        svc.issue_token_pair(user)

    kwargs = mock_cat.call_args.kwargs
    assert "jti" in kwargs and kwargs["jti"]


def test_issue_token_pair_calls_issue_refresh_token() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)

    with patch("app.services.auth_service.security.create_access_token", return_value="tok"):
        svc.issue_token_pair(user)

    svc._token_service.issue_refresh_token.assert_called_once()
    kwargs = svc._token_service.issue_refresh_token.call_args.kwargs
    assert kwargs["user_id"] == str(user.id)
    assert kwargs["role"] == user.role.value


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_register_returns_user_access_refresh() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)

    with patch("app.services.auth_service.security.hash_password", return_value="hashed"), \
         patch("app.services.auth_service.security.create_access_token", return_value="at"):
        result_user, access, refresh = svc.register(
            email="alice@example.com",
            password="password1",
            full_name="Alice",
            organization_name="ACME Corp",
            tenant_slug="acme",
        )

    assert result_user is user
    assert access == "at"
    assert refresh == "refresh-tok"


def test_register_raises_conflict_when_slug_taken() -> None:
    existing_tenant = MagicMock()
    svc = _make_auth_service(tenant=existing_tenant, slug_taken=True)

    with pytest.raises(ConflictError):
        svc.register(
            email="alice@example.com",
            password="password1",
            full_name=None,
            organization_name="ACME",
            tenant_slug="acme",
        )


def test_register_raises_validation_on_empty_slug() -> None:
    svc = _make_auth_service()

    with pytest.raises(ValidationError):
        svc.register(
            email="a@b.com",
            password="pass1234",
            full_name=None,
            organization_name="Org",
            tenant_slug="",
        )


def test_register_raises_validation_on_blank_org_name() -> None:
    svc = _make_auth_service()

    with pytest.raises(ValidationError):
        svc.register(
            email="a@b.com",
            password="pass1234",
            full_name=None,
            organization_name="   ",
            tenant_slug="myslug",
        )


def test_register_normalizes_slug_to_lowercase() -> None:
    svc = _make_auth_service()
    captured_slugs: list[str] = []

    def _capture_slug(s: str) -> None:
        captured_slugs.append(s)
        return None  # not taken

    svc._tenant_repo.get_by_slug.side_effect = _capture_slug

    with patch("app.services.auth_service.security.hash_password", return_value="h"), \
         patch("app.services.auth_service.security.create_access_token", return_value="t"):
        try:
            svc.register(
                email="a@b.com",
                password="password1",
                full_name=None,
                organization_name="Org",
                tenant_slug="MySlug",  # mixed case
            )
        except Exception:
            pass  # user_repo.create might fail — we only care about slug normalization

    assert captured_slugs[0] == "myslug"


# ---------------------------------------------------------------------------
# refresh_tokens()
# ---------------------------------------------------------------------------


def test_refresh_tokens_returns_new_pair_on_valid_token() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)
    svc._token_service.consume_refresh_token.return_value = {
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": "admin",
    }

    with patch("app.services.auth_service.security.create_access_token", return_value="new-at"):
        result_user, access, refresh = svc.refresh_tokens("old-refresh")

    assert result_user is user
    assert access == "new-at"
    assert refresh == "refresh-tok"


def test_refresh_tokens_raises_validation_on_invalid_token() -> None:
    svc = _make_auth_service()
    svc._token_service.consume_refresh_token.return_value = None

    with pytest.raises(ValidationError):
        svc.refresh_tokens("bad-token")


def test_refresh_tokens_raises_validation_on_inactive_user() -> None:
    inactive_user = _make_user(is_active=False)
    svc = _make_auth_service(user=inactive_user)
    svc._token_service.consume_refresh_token.return_value = {
        "user_id": str(inactive_user.id),
        "tenant_id": str(inactive_user.tenant_id),
        "role": "admin",
    }

    with pytest.raises(ValidationError):
        svc.refresh_tokens("old-refresh")


def test_refresh_tokens_consumes_old_token() -> None:
    user = _make_user()
    svc = _make_auth_service(user=user)
    svc._token_service.consume_refresh_token.return_value = {
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": "admin",
    }

    with patch("app.services.auth_service.security.create_access_token", return_value="t"):
        svc.refresh_tokens("the-token")

    svc._token_service.consume_refresh_token.assert_called_once_with("the-token")


# ---------------------------------------------------------------------------
# logout()
# ---------------------------------------------------------------------------


def test_logout_denylists_access_token() -> None:
    svc = _make_auth_service()
    future_exp = int(time.time()) + 3600

    svc.logout(jti="jti-xyz", token_exp_timestamp=future_exp)

    svc._token_service.denylist_access_token.assert_called_once()
    call_kwargs = svc._token_service.denylist_access_token.call_args
    jti_arg = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("jti")
    assert jti_arg == "jti-xyz"


def test_logout_also_revokes_refresh_token_when_provided() -> None:
    svc = _make_auth_service()
    future_exp = int(time.time()) + 3600

    svc.logout(jti="j1", token_exp_timestamp=future_exp, refresh_token="rt-abc")

    svc._token_service.revoke_refresh_token.assert_called_once_with("rt-abc")


def test_logout_skips_refresh_revocation_when_not_provided() -> None:
    svc = _make_auth_service()

    svc.logout(jti="j1", token_exp_timestamp=int(time.time()) + 60)

    svc._token_service.revoke_refresh_token.assert_not_called()


def test_logout_noop_when_jti_is_none() -> None:
    svc = _make_auth_service()

    svc.logout(jti=None, token_exp_timestamp=None)

    svc._token_service.denylist_access_token.assert_not_called()
