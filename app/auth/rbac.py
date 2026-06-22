"""FastAPI RBAC dependency: enforce that the current user holds permissions.

``require_permissions`` is a dependency *factory*: call it with one or more
:class:`app.auth.permissions.Permission` values to obtain a FastAPI dependency
that resolves the authenticated user (via
:func:`app.core.security.get_current_user`) and rejects the request with a
:class:`app.core.exceptions.ForbiddenError` (HTTP 403) unless the user's role is
granted *every* requested permission (logical AND).

Example
-------
    @router.get("/users", dependencies=[Depends(require_permissions(Permission.USER_READ))])
    def list_users(...):
        ...

Or to also consume the user object::

    @router.post("/users")
    def create_user(user: User = Depends(require_permissions(Permission.USER_WRITE))):
        ...
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends

from app.auth.permissions import Permission, has_permission
from app.core.exceptions import ForbiddenError
from app.core.security import get_current_user
from app.models.user import User
from app.observability.logging import get_logger

logger = get_logger(__name__)


def require_permissions(*perms: Permission) -> Callable[..., User]:
    """Build a FastAPI dependency enforcing all of ``perms`` for the caller.

    Returns the authenticated :class:`app.models.user.User` on success so the
    dependency can double as a current-user provider. Raises
    :class:`ForbiddenError` if the user's role lacks any required permission.

    Passing no permissions yields an authentication-only gate (any logged-in
    user passes), which is occasionally useful for "must be signed in" routes.
    """

    required: tuple[Permission, ...] = perms

    def dependency(user: User = Depends(get_current_user)) -> User:
        # Identify the missing permissions (if any) for precise diagnostics.
        missing = [perm for perm in required if not has_permission(user.role, perm)]
        if missing:
            missing_values = [perm.value for perm in missing]
            logger.warning(
                "Permission denied",
                user_id=str(getattr(user, "id", "unknown")),
                role=getattr(user.role, "value", str(user.role)),
                missing=missing_values,
            )
            raise ForbiddenError(
                message="You do not have permission to perform this action.",
                details={"missing_permissions": missing_values},
            )
        return user

    return dependency


__all__ = ["require_permissions"]
