"""Request-local security context: current tenant and current acting user.

The platform is multi-tenant. The *current* tenant and *current user* for a unit
of work are held in :class:`contextvars.ContextVar` objects so they propagate
correctly across async tasks and stay isolated per request. Middleware/auth set
them at the start of a request and reset them in a ``finally`` block;
persistence code reads them to scope queries and to push Postgres GUCs for
Row-Level Security (RLS) and audit attribution.

GUCs (applied per transaction by :mod:`app.db.session`):
  * ``app.current_tenant``   — consulted by RLS policies (ADR-001).
  * ``app.current_user_id``  — the acting principal, used for audit/event
    attribution (``created_by``/``updated_by``/``actor_user_id``/event ``user_id``).

``PLATFORM_TENANT_ID`` is the nil UUID and represents platform-level (global,
cross-tenant) operations such as administrative tooling.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.observability.logging import get_logger

logger = get_logger(__name__)

# The nil UUID denotes the platform / global scope (no specific tenant).
PLATFORM_TENANT_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Request-local current tenant. ``None`` means "no tenant resolved yet".
_current_tenant: ContextVar[uuid.UUID | None] = ContextVar("current_tenant", default=None)

# Request-local current acting user. ``None`` means "system / unauthenticated".
_current_user: ContextVar[uuid.UUID | None] = ContextVar("current_user", default=None)

# Names of the Postgres run-time parameters.
_TENANT_GUC = "app.current_tenant"
_USER_GUC = "app.current_user_id"


def get_current_tenant() -> uuid.UUID | None:
    """Return the tenant bound to the current context, or ``None``."""
    return _current_tenant.get()


def set_current_tenant(tenant_id: uuid.UUID | None) -> Token[uuid.UUID | None]:
    """Bind ``tenant_id`` to the current context and return a reset token.

    The returned :class:`contextvars.Token` MUST be passed to
    :func:`reset_current_tenant` (typically in a ``finally`` block) to restore
    the previous value and avoid leaking tenant scope across requests.
    """
    return _current_tenant.set(tenant_id)


def reset_current_tenant(token: Token[uuid.UUID | None]) -> None:
    """Restore the tenant context to the state captured by ``token``."""
    _current_tenant.reset(token)


def get_current_user_id() -> uuid.UUID | None:
    """Return the acting user bound to the current context, or ``None``."""
    return _current_user.get()


def set_current_user_id(user_id: uuid.UUID | None) -> Token[uuid.UUID | None]:
    """Bind the acting ``user_id`` to the current context; returns a reset token.

    Mirrors :func:`set_current_tenant`. Used for audit/event attribution; the
    token SHOULD be reset in a ``finally`` block to avoid leaking the actor
    across requests served on the same worker task.
    """
    return _current_user.set(user_id)


def reset_current_user_id(token: Token[uuid.UUID | None]) -> None:
    """Restore the current-user context to the state captured by ``token``."""
    _current_user.reset(token)


def apply_tenant_guc(session: Session, tenant_id: uuid.UUID) -> None:
    """Issue ``SET LOCAL app.current_tenant`` so RLS policies can read it.

    ``SET LOCAL`` scopes the parameter to the current transaction, so the value
    is automatically discarded on commit/rollback. This is best-effort: the
    surrounding application logic should still scope queries explicitly. On any
    database error (for example, a backend that does not support the GUC) the
    failure is logged and swallowed rather than aborting the request.
    """

    try:
        # Bind the UUID as a string parameter to avoid SQL injection and to let
        # the driver handle quoting. ``set_config(name, value, is_local=true)``
        # is the parameterizable equivalent of ``SET LOCAL``.
        session.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": _TENANT_GUC, "value": str(tenant_id)},
        )
        logger.debug("Applied tenant GUC", tenant_id=str(tenant_id), guc=_TENANT_GUC)
    except SQLAlchemyError as exc:
        # RLS GUC is an enhancement, not a hard requirement; never break the
        # request because the parameter could not be set.
        logger.warning(
            "Failed to apply tenant GUC; continuing without RLS scope",
            tenant_id=str(tenant_id),
            guc=_TENANT_GUC,
            error=str(exc),
        )


__all__ = [
    "PLATFORM_TENANT_ID",
    "get_current_tenant",
    "set_current_tenant",
    "reset_current_tenant",
    "get_current_user_id",
    "set_current_user_id",
    "reset_current_user_id",
    "apply_tenant_guc",
]
