"""Security utilities: password hashing, JWT issuance, and RBAC dependencies.

This module is part of the Mesaar backend foundation. The public surface
(``hash_password``, ``verify_password``, ``create_access_token``,
``decode_access_token``, ``get_current_user``, ``require_roles``) is a hard
compatibility contract relied upon by existing application code and other
foundation generators; their signatures must never change.

Backward-compatible additions only: ``decode_access_token`` tolerates the
optional ``iss``/``aud`` claims that the richer token service in
``app.auth.tokens`` emits, but never *requires* them, so legacy access tokens
minted by :func:`create_access_token` continue to validate unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redis import get_redis
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
    expire = datetime.now(tz=timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
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


def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    """Resolve the current authenticated user from the JWT."""
    payload = decode_access_token(token)

    # Reject denylisted tokens (logout revocation path).  Redis errors are
    # logged and swallowed — the denylist is a defence-in-depth control, not a
    # hard dependency; a Redis outage must not block authentication.
    _jti = payload.get("jti")
    if _jti:
        try:
            if get_redis().exists(f"denylist:{_jti}") > 0:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception as _exc:
            logger.warning("Denylist check skipped — Redis unavailable: {}", _exc)

    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Bind the tenant from the token BEFORE any query so Row-Level Security
    # scopes the user lookup (and everything after) to the caller's tenant
    # (ADR-001). Tokens without a ``tid`` run platform-scoped (e.g. legacy).
    tenant_claim = payload.get("tid")
    if tenant_claim is not None:
        try:
            set_current_tenant(uuid.UUID(str(tenant_claim)))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
    # Bind the acting user for audit/event attribution (app.current_user_id).
    try:
        set_current_user_id(uuid.UUID(str(user_id)))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    repo = UserRepository(session)
    user = repo.get_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


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
