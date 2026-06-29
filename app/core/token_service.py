"""Refresh-token issuance / rotation and access-token denylist via Redis.

Refresh tokens are opaque UUID strings stored in Redis as:
  ``refresh:{token_id}``  →  JSON ``{user_id, tenant_id, role}``  [TTL = refresh lifetime]

Access-token denylist entries:
  ``denylist:{jti}``  →  ``"1"``  [TTL = remaining access-token lifetime]

Key-prefix isolation means a targeted ``SCAN MATCH denylist:*`` or
``SCAN MATCH refresh:*`` will never accidentally touch the other namespace.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

import redis as redis_lib

from app.core.config import get_settings

_REFRESH_PREFIX = "refresh"
_DENYLIST_PREFIX = "denylist"


class TokenService:
    """Manages refresh-token lifecycle and access-token revocation in Redis."""

    def __init__(self, redis: redis_lib.Redis) -> None:
        self._redis = redis
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Refresh tokens
    # ------------------------------------------------------------------

    def issue_refresh_token(
        self,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> str:
        """Generate, store, and return an opaque refresh token string.

        The token is a random UUID stored with the user's identity payload.
        TTL equals ``refresh_token_expire_minutes`` from :class:`Settings`.
        """
        token_id = str(uuid.uuid4())
        key = f"{_REFRESH_PREFIX}:{token_id}"
        payload = json.dumps({"user_id": user_id, "tenant_id": tenant_id, "role": role})
        ttl = self._settings.refresh_token_expire_minutes * 60
        self._redis.setex(key, ttl, payload)
        return token_id

    def consume_refresh_token(self, token: str) -> Optional[dict]:
        """Atomically consume a refresh token and return its payload.

        Uses ``GETDEL`` so the key is deleted in the same atomic operation,
        preventing replay attacks.  Returns ``None`` when the token is absent,
        expired, or already consumed.
        """
        key = f"{_REFRESH_PREFIX}:{token}"
        raw = self._redis.getdel(key)
        if raw is None:
            return None
        return json.loads(raw)

    def revoke_refresh_token(self, token: str) -> None:
        """Immediately delete a refresh token (e.g. on explicit logout)."""
        self._redis.delete(f"{_REFRESH_PREFIX}:{token}")

    # ------------------------------------------------------------------
    # Access-token denylist
    # ------------------------------------------------------------------

    def denylist_access_token(self, jti: str, ttl_seconds: int) -> None:
        """Add an access token's JTI to the revocation denylist.

        The entry expires automatically when the access token's natural
        lifetime ends, keeping the denylist small.  No-op if ``ttl_seconds``
        is zero or negative (token already expired).
        """
        if ttl_seconds <= 0:
            return
        self._redis.setex(f"{_DENYLIST_PREFIX}:{jti}", ttl_seconds, "1")

    def is_denylisted(self, jti: str) -> bool:
        """Return ``True`` when the JTI is present in the active denylist."""
        return self._redis.exists(f"{_DENYLIST_PREFIX}:{jti}") > 0
