"""Authentication and authorization infrastructure for the Mesaar platform.

This package provides foundation-level auth building blocks only — token
issuance/rotation, a generic RBAC permission catalogue, and FastAPI
dependencies that enforce permissions. It intentionally contains *no* business
policy: domain authorization rules live in the service layer.

Public submodules:
    - :mod:`app.auth.tokens`       — access/refresh token pairs + revocation.
    - :mod:`app.auth.permissions`  — generic ``Permission`` enum + role map.
    - :mod:`app.auth.rbac`         — ``require_permissions`` FastAPI dependency.
"""

from __future__ import annotations

from app.auth.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    has_permission,
)
from app.auth.rbac import require_permissions
from app.auth.tokens import (
    TokenPair,
    TokenType,
    create_refresh_token,
    create_token_pair,
    decode_token,
    is_refresh_revoked,
    revoke_refresh,
    rotate_refresh_token,
)

__all__ = [
    "Permission",
    "ROLE_PERMISSIONS",
    "has_permission",
    "require_permissions",
    "TokenType",
    "TokenPair",
    "create_token_pair",
    "create_refresh_token",
    "decode_token",
    "revoke_refresh",
    "is_refresh_revoked",
    "rotate_refresh_token",
]
