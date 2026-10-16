"""Security utilities: password hashing, JWT issuance, and RBAC dependencies.

This module is part of the Mesaar backend foundation. The public surface
(``hash_password``, ``verify_password``, ``create_access_token``,
``decode_access_token``, ``get_current_user``, ``require_roles``) is a hard
compatibility contract relied upon by existing application code and other
foundation generators; their signatures must never change.

Refresh tokens and the access-token denylist live in
:mod:`app.core.token_service` (opaque Redis-backed tokens).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.token_service import TokenService
from app.db.session import get_session
from app.db.tenant import set_current_tenant, set_current_user_id
from app.models.enums import UserRole
from app.models.user import User
from app.observability.logging import get_logger
from app.repositories.user_repository import UserRepository

logger = get_logger(__name__)

# OAuth2PasswordBearer defines where the client obtains a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Centralized password hashing context; bcrypt is widely vetted and slow-hash friendly.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a bcrypt hash for the provided plaintext password."""
    settings = get_settings()
    # passlib requires the scheme-prefixed keyword (``bcrypt__rounds``) on
    # ``using()``; a bare ``rounds=`` raises KeyError("unknown CryptContext
    # keyword").
    return pwd_context.using(bcrypt__rounds=settings.bcrypt_work_factor).hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check plaintext password against stored hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    *,
    subject: str,
    role: str,
    tenant_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
    jti: Optional[str] = None,
) -> str:
    """Create a signed JWT access token.

    ``tenant_id`` is an additive, backward-compatible claim (``tid``): when
    present it scopes the authenticated principal to a tenant so Row-Level
    Security can be applied before any database read (ADR-001). Tokens minted
    without it (legacy / platform) simply omit the claim.
    """
    settings = get_settings()
    issued_at = utcnow()
    expire = issued_at + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "iat": issued_at,
    }
    if tenant_id is not None:
        to_encode["tid"] = tenant_id
    if jti is not None:
        to_encode["jti"] = jti
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.token_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT, raising HTTP 401 on failure."""
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.token_algorithm],
        )
    except JWTError as exc:  # pragma: no cover - runtime path
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=_UNAUTHORIZED_HEADERS,
    )


@dataclass(frozen=True)
class _AuthenticatedPrincipal:
    user: User
    tenant_id: Optional[uuid.UUID]
    user_id: uuid.UUID


def _authenticate(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> _AuthenticatedPrincipal:
    """Validate the JWT and load the active user (sync: runs in the threadpool).

    The tenant/user ContextVars set here only cover the user lookup itself:
    FastAPI runs sync dependencies inside a *copy* of the request context, so
    anything set here is discarded on return. :func:`get_current_user` re-binds
    them in the request context.
    """
    payload = decode_access_token(token)

    # Reject denylisted tokens (logout revocation path). The denylist is a
    # defence-in-depth control, not a hard dependency: a Redis outage is logged
    # and must not block authentication.
    jti = payload.get("jti")
    if jti:
        try:
            if TokenService(get_redis()).is_denylisted(jti):
                raise _unauthorized("Token has been revoked.")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Denylist check skipped — Redis unavailable: {}", exc)

    subject: Optional[str] = payload.get("sub")
    if subject is None:
        raise _unauthorized("Malformed token.")
    try:
        user_id = uuid.UUID(str(subject))
        tenant_claim = payload.get("tid")
        tenant_id = uuid.UUID(str(tenant_claim)) if tenant_claim is not None else None
    except ValueError as exc:
        raise _unauthorized("Malformed token.") from exc

    # Bind the token tenant BEFORE any query so RLS scopes the user lookup to
    # the caller's tenant (ADR-001). Tokens without ``tid`` run platform-scoped.
    if tenant_id is not None:
        set_current_tenant(tenant_id)
    set_current_user_id(user_id)

    user = UserRepository(session).get_by_id(str(user_id))
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive.")
    return _AuthenticatedPrincipal(user=user, tenant_id=tenant_id, user_id=user_id)


async def get_current_user(principal: _AuthenticatedPrincipal = Depends(_authenticate)) -> User:
    """Resolve the authenticated user and bind tenant/user to the request context.

    Deliberately ``async``: FastAPI awaits async dependencies inside the request
    task, so the ContextVars set here are visible to the endpoint and every
    service it calls (tenant-scoped writes, the RLS GUC on each later
    transaction, audit attribution). The token tenant always overrides any
    client-supplied ``X-Tenant-ID`` header bound by the middleware.
    """
    if principal.tenant_id is not None:
        set_current_tenant(principal.tenant_id)
    set_current_user_id(principal.user_id)
    return principal.user


def require_roles(*roles: UserRole):
    """Dependency factory enforcing that current user has one of the allowed roles."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if roles and user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this operation.",
            )
        return user

    return dependency
