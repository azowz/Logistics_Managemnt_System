"""JWT token service: access/refresh issuance, validation, rotation, revocation.

Design notes
------------
* Access tokens are minted via :func:`app.core.security.create_access_token`
  so signing key/algorithm/expiry stay single-sourced. We additively decorate
  them with ``iss``/``aud``/``type`` claims via a re-encode pass, never by
  changing the security module's signature.
* Refresh tokens are long-lived, carry a unique ``jti``, and are revocable.
  Revocation uses a Redis denylist (``app.core.redis``) keyed by ``jti`` with
  a TTL matching the token's remaining lifetime, so expired entries self-purge.
* Rotation (:func:`rotate_refresh_token`) validates the presented refresh
  token, revokes its ``jti``, and issues a brand-new pair — the standard
  refresh-token rotation pattern that limits replay windows.
* All validation failures raise :class:`app.core.exceptions.AuthError` (HTTP
  401), never a bare ``JWTError``, so the API surfaces a uniform envelope.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any, Optional

from jose import JWTError, jwt

from app.common.datetime import utcnow
from app.core.config import get_settings
from app.core.exceptions import AuthError
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Redis key namespace for the refresh-token jti denylist.
_REVOKED_KEY_PREFIX = "auth:refresh:revoked:"


class TokenType(str, Enum):
    """Discriminator embedded in the ``type`` claim of every token."""

    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(slots=True)
class TokenPair:
    """An issued access + refresh token pair returned to clients.

    ``expires_in`` is the *access* token lifetime in seconds, per OAuth2
    conventions, so clients know when to refresh.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0


def _revoked_key(jti: str) -> str:
    """Build the Redis denylist key for a refresh-token ``jti``."""
    return f"{_REVOKED_KEY_PREFIX}{jti}"


def _decorate_access_token(token: str) -> str:
    """Re-sign an access token adding ``iss``/``aud``/``type`` claims.

    The base token from :func:`create_access_token` already contains
    ``sub``/``role``/``exp``/``iat``. We decode it without verification of
    aud (none present yet), enrich the payload, and re-encode with the same
    signing material. This keeps the security module's public API frozen while
    still emitting issuer/audience-aware tokens.
    """

    settings = get_settings()
    try:
        # The base token was just signed by us; verify signature/exp to be safe
        # but do not require iss/aud (they are absent at this stage).
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.token_algorithm],
            options={"verify_aud": False},
        )
    except JWTError as exc:  # pragma: no cover - we just minted this token
        logger.error("Failed to decode freshly minted access token", error=str(exc))
        raise AuthError(message="Could not issue access token.") from exc

    payload.update(
        {
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "type": TokenType.ACCESS.value,
        }
    )
    return jwt.encode(payload, settings.secret_key, algorithm=settings.token_algorithm)


def create_refresh_token(subject: str) -> str:
    """Create a signed, revocable refresh token for ``subject``.

    Carries a unique ``jti`` (used for denylist revocation), ``type=refresh``,
    issuer/audience, and an expiry derived from
    ``settings.refresh_token_expire_minutes``.
    """

    settings = get_settings()
    now = utcnow()
    expire = now + timedelta(minutes=settings.refresh_token_expire_minutes)
    jti = uuid.uuid4().hex

    payload: dict[str, Any] = {
        "sub": subject,
        "jti": jti,
        "type": TokenType.REFRESH.value,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": expire,
    }
    logger.debug("Issuing refresh token", subject=subject, jti=jti)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.token_algorithm)


def create_token_pair(subject: str, role: str) -> TokenPair:
    """Issue a fresh access+refresh :class:`TokenPair` for ``subject``/``role``."""

    settings = get_settings()
    access_token = _decorate_access_token(create_access_token(subject=subject, role=role))
    refresh_token = create_refresh_token(subject)
    expires_in = settings.access_token_expire_minutes * 60

    logger.info("Issued token pair", subject=subject, role=role)
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


def decode_token(token: str, expected_type: Optional[TokenType] = None) -> dict[str, Any]:
    """Decode and fully validate a token, returning its claims.

    Validates signature, expiry, issuer, and audience. When ``expected_type``
    is provided, the ``type`` claim must match exactly. On any failure a
    :class:`AuthError` (HTTP 401) is raised — callers never see ``JWTError``.
    """

    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.token_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except JWTError as exc:
        logger.warning("Token validation failed", error=str(exc))
        raise AuthError(message="Invalid or expired token.") from exc

    if expected_type is not None:
        token_type = payload.get("type")
        if token_type != expected_type.value:
            logger.warning(
                "Token type mismatch",
                expected=expected_type.value,
                actual=token_type,
            )
            raise AuthError(message="Unexpected token type.")

    return payload


def revoke_refresh(jti: str) -> None:
    """Add a refresh-token ``jti`` to the Redis denylist.

    The denylist entry is given a TTL equal to the maximum remaining refresh
    lifetime so it self-expires once the token could no longer be valid,
    preventing unbounded key growth. Failures are logged and re-raised as
    :class:`AuthError` because a silent revocation failure is a security risk.
    """

    settings = get_settings()
    ttl_seconds = settings.refresh_token_expire_minutes * 60
    try:
        client = get_redis()
        client.set(_revoked_key(jti), "1", ex=ttl_seconds)
        logger.info("Refresh token revoked", jti=jti)
    except Exception as exc:  # noqa: BLE001 - convert any backend error to AuthError
        logger.error("Failed to revoke refresh token", jti=jti, error=str(exc))
        raise AuthError(message="Could not revoke refresh token.") from exc


def is_refresh_revoked(jti: str) -> bool:
    """Return ``True`` if a refresh-token ``jti`` is on the denylist.

    Fails *closed*: if Redis is unreachable we treat the token as revoked,
    because allowing a token we cannot check would defeat revocation.
    """

    try:
        client = get_redis()
        return client.exists(_revoked_key(jti)) > 0
    except Exception as exc:  # noqa: BLE001 - unavailable backend -> deny
        logger.error("Revocation check failed; failing closed", jti=jti, error=str(exc))
        return True


def rotate_refresh_token(refresh_token: str) -> TokenPair:
    """Validate, revoke, and replace a refresh token (rotation pattern).

    Steps:
        1. Decode + validate the token as a refresh token.
        2. Reject if its ``jti`` is already on the denylist (replay).
        3. Revoke the old ``jti``.
        4. Issue a brand-new access+refresh pair for the same subject.

    The new access token carries no role claim from the refresh token (refresh
    tokens are intentionally role-free); callers that need a role-bearing
    access token should re-derive role from the user record. To keep the
    foundation self-contained we mint the access token with the subject as the
    role-agnostic principal and an empty role, which downstream auth replaces.
    """

    payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)

    jti = payload.get("jti")
    subject = payload.get("sub")
    if not isinstance(jti, str) or not isinstance(subject, str):
        logger.warning("Refresh token missing jti/sub", has_jti=bool(jti), has_sub=bool(subject))
        raise AuthError(message="Malformed refresh token.")

    if is_refresh_revoked(jti):
        logger.warning("Attempt to rotate a revoked refresh token", jti=jti)
        raise AuthError(message="Refresh token has been revoked.")

    # Invalidate the presented token before issuing a replacement.
    revoke_refresh(jti)

    # Preserve any role hint the refresh token carried (normally absent).
    role = payload.get("role")
    role_value = role if isinstance(role, str) else ""

    new_pair = create_token_pair(subject=subject, role=role_value)
    logger.info("Rotated refresh token", subject=subject, old_jti=jti)
    return new_pair


__all__ = [
    "TokenType",
    "TokenPair",
    "create_token_pair",
    "create_refresh_token",
    "decode_token",
    "revoke_refresh",
    "is_refresh_revoked",
    "rotate_refresh_token",
]
