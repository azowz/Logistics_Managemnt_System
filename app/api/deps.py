"""Shared FastAPI dependencies.

Provides the cross-cutting dependency providers wired into route handlers:

* :func:`get_current_driver` -- resolves the :class:`~app.models.driver.Driver`
  profile for an authenticated driver-role user (PRESERVED public API).
* :func:`get_settings_dep` -- exposes cached application settings via DI.
* :func:`get_redis_client` -- exposes the cached Redis singleton via DI.
* :func:`get_tenant_id` -- resolves the active tenant from request context.
* :func:`get_page_params` -- standard pagination parameters dependency.

Keeping these in one module lets routers depend on stable, testable callables
that can be overridden in tests via FastAPI's ``dependency_overrides``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.db.session import get_session
from app.db.tenant import get_current_tenant
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.driver_repository import DriverRepository

if TYPE_CHECKING:  # pragma: no cover - typing only.
    import redis


def get_current_driver(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Driver:
    """Resolve the Driver profile for the authenticated driver-role user."""
    if user.role != UserRole.DRIVER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is for drivers only.",
        )
    driver = DriverRepository(session).get_by_user_id(str(user.id))
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driver profile linked to this account.",
        )
    return driver


def get_settings_dep() -> Settings:
    """Provide the cached application :class:`~app.core.config.Settings`.

    Thin wrapper over :func:`app.core.config.get_settings` so handlers can write
    ``settings: Settings = Depends(get_settings_dep)`` and so tests can override
    settings through ``app.dependency_overrides`` without monkeypatching the
    module-level cache.
    """

    return get_settings()


def get_redis_client() -> "redis.Redis":
    """Provide the cached, process-wide Redis client as a dependency.

    Delegates to :func:`app.core.redis.get_redis`. Exposed as a dependency so
    routes obtain Redis through DI (and tests can inject a fake) rather than
    importing the singleton directly.
    """

    return get_redis()


def get_tenant_id() -> uuid.UUID | None:
    """Return the tenant id bound to the current request context, if any.

    The tenant is populated by
    :class:`~app.api.middleware.request_context.RequestContextMiddleware` from
    the configured tenant header. Returns ``None`` for unscoped / platform
    requests; route handlers that require a tenant should validate accordingly.
    """

    return get_current_tenant()


def get_page_params(params: PageParams = Depends()) -> PageParams:
    """Provide standard, bounded pagination parameters.

    :class:`~app.common.pagination.PageParams` already validates ``page``/``size``
    bounds; this indirection gives a single, stable dependency name that list
    endpoints can share and tests can override.
    """

    return params


__all__ = [
    "get_current_driver",
    "get_settings_dep",
    "get_redis_client",
    "get_tenant_id",
    "get_page_params",
]
