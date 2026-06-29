"""Authentication and registration service.

Handles:
* Credential verification (login).
* Self-service tenant + admin-user registration.
* Token-pair issuance (access + refresh).
* Refresh-token rotation.
* Access-token revocation (logout denylist).

This service owns its unit of work.  It does not import FastAPI or HTTP types;
error signalling uses domain exceptions from :mod:`app.services.exceptions`.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.token_service import TokenService
from app.models.enums import UserRole
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository
from app.services.exceptions import ConflictError, ValidationError


class AuthService:
    """Handles credential verification, registration, and token lifecycle."""

    def __init__(
        self,
        session: Session,
        *,
        redis=None,
    ) -> None:
        self._session = session
        self._user_repo = UserRepository(session)
        self._tenant_repo = TenantRepository(session)
        self._settings = get_settings()

        # Lazy Redis import so tests that do not need Redis can skip it.
        if redis is None:
            from app.core.redis import get_redis
            redis = get_redis()
        self._token_service = TokenService(redis)

    # ------------------------------------------------------------------
    # Credential verification (backward-compatible)
    # ------------------------------------------------------------------

    def authenticate(
        self,
        email: str,
        password: str,
        *,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> Optional[User]:
        """Validate credentials and return the User on success, or None.

        When ``tenant_id`` is supplied the lookup is scoped to that tenant
        so that two tenants sharing the same email address do not collide.
        Without it the query relies on RLS (platform scope at login time)
        to return the first match.
        """
        user = self._user_repo.get_by_email(email=email, tenant_id=tenant_id)
        if user is None or not user.is_active:
            return None
        if not security.verify_password(password, user.hashed_password):
            return None
        return user

    # ------------------------------------------------------------------
    # Token issuance
    # ------------------------------------------------------------------

    def create_access_token(self, user: User) -> str:
        """Issue a signed JWT access token (no refresh token).

        Kept for backward compatibility.  Prefer :meth:`issue_token_pair`
        for all new call sites so that a refresh token is also returned.
        """
        expiry = timedelta(minutes=self._settings.access_token_expire_minutes)
        return security.create_access_token(
            subject=str(user.id),
            role=user.role.value,
            tenant_id=str(user.tenant_id) if user.tenant_id else None,
            expires_delta=expiry,
        )

    def issue_token_pair(self, user: User) -> Tuple[str, str]:
        """Issue a (access_token, refresh_token) pair for ``user``.

        The access token carries a ``jti`` claim so it can be revoked via the
        denylist on logout.  The refresh token is stored in Redis with a TTL
        equal to :attr:`Settings.refresh_token_expire_minutes`.
        """
        jti = str(uuid.uuid4())
        expiry = timedelta(minutes=self._settings.access_token_expire_minutes)
        access_token = security.create_access_token(
            subject=str(user.id),
            role=user.role.value,
            tenant_id=str(user.tenant_id) if user.tenant_id else None,
            expires_delta=expiry,
            jti=jti,
        )
        refresh_token = self._token_service.issue_refresh_token(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id) if user.tenant_id else "",
            role=user.role.value,
        )
        return access_token, refresh_token

    # ------------------------------------------------------------------
    # Self-service registration
    # ------------------------------------------------------------------

    def register(
        self,
        *,
        email: str,
        password: str,
        full_name: Optional[str],
        organization_name: str,
        tenant_slug: str,
    ) -> Tuple[User, str, str]:
        """Create a new tenant + admin user in a single transaction.

        Returns ``(user, access_token, refresh_token)`` on success.

        Raises:
            :class:`ConflictError`: when the ``tenant_slug`` is already taken.
            :class:`ValidationError`: when the slug or org name is blank.
        """
        slug_norm = (tenant_slug or "").strip().lower()
        if not slug_norm:
            raise ValidationError("Tenant slug is required.")
        if not (organization_name or "").strip():
            raise ValidationError("Organization name is required.")

        if self._tenant_repo.get_by_slug(slug_norm) is not None:
            raise ConflictError(f"Tenant slug already exists: {slug_norm!r}.")

        # Create tenant (flush only — no commit yet).
        tenant = Tenant(
            slug=slug_norm,
            name=organization_name.strip(),
            status="active",
            isolation_mode="shared",
        )
        self._tenant_repo.add(tenant)  # add() calls flush internally → tenant.id is available

        # Create admin user in the new tenant (commit covers both).
        user = self._user_repo.create(
            tenant_id=tenant.id,
            email=email,
            full_name=full_name,
            hashed_password=security.hash_password(password),
            role=UserRole.ADMIN,
            is_active=True,
        )

        access_token, refresh_token = self.issue_token_pair(user)
        return user, access_token, refresh_token

    # ------------------------------------------------------------------
    # Refresh-token rotation
    # ------------------------------------------------------------------

    def refresh_tokens(self, refresh_token: str) -> Tuple[User, str, str]:
        """Exchange a valid refresh token for a new (access, refresh) pair.

        The old refresh token is consumed atomically (GETDEL) so it cannot be
        reused.  A new refresh token is issued with the same TTL.

        Raises:
            :class:`ValidationError`: when the token is invalid or expired.
        """
        data = self._token_service.consume_refresh_token(refresh_token)
        if data is None:
            raise ValidationError("Invalid or expired refresh token.")

        user = self._user_repo.get_by_id(data["user_id"])
        if user is None or not user.is_active:
            raise ValidationError("User not found or account is inactive.")

        access_token, new_refresh_token = self.issue_token_pair(user)
        return user, access_token, new_refresh_token

    # ------------------------------------------------------------------
    # Logout / token revocation
    # ------------------------------------------------------------------

    def logout(
        self,
        *,
        jti: Optional[str],
        token_exp_timestamp: Optional[int],
        refresh_token: Optional[str] = None,
    ) -> None:
        """Revoke the current access token and optionally the refresh token.

        The access token's JTI is added to the Redis denylist with a TTL equal
        to the remaining lifetime of the token.  When ``refresh_token`` is also
        provided it is deleted from Redis immediately.

        Args:
            jti: The ``jti`` claim from the access token payload.
            token_exp_timestamp: The ``exp`` claim (Unix timestamp) from the
                access token payload; used to compute the denylist TTL.
            refresh_token: If present, the corresponding Redis key is deleted.
        """
        if jti and token_exp_timestamp is not None:
            remaining = int(token_exp_timestamp) - int(time.time())
            self._token_service.denylist_access_token(jti, remaining)

        if refresh_token:
            self._token_service.revoke_refresh_token(refresh_token)
