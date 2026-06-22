"""Generic RBAC permission catalogue and role-to-permission mapping.

This is *infrastructure* RBAC, not business policy. It defines a small,
stable set of coarse-grained permissions and maps the existing
:class:`app.models.enums.UserRole` values onto them. No database tables, no
policy rows, no per-resource ACLs — those belong in the service/domain layer.

The mapping is deliberately conservative:

    * ``admin``   — full platform control.
    * ``manager`` — operational read/write across users, fleet, shipments.
    * ``driver``  — self-service plus shipment read (their assigned work).
    * ``client``  — shipment read (their own orders, scoped by the service).

Downstream code should depend on :func:`has_permission` rather than reading the
``ROLE_PERMISSIONS`` table directly, so the resolution strategy can evolve.
"""

from __future__ import annotations

from enum import Enum

from app.models.enums import UserRole
from app.observability.logging import get_logger

logger = get_logger(__name__)


class Permission(str, Enum):
    """Coarse-grained, generic capabilities enforced by the RBAC layer.

    Values are stable string identifiers safe to embed in tokens, logs, and
    audit trails. Keep this set SMALL and infrastructural — do not add
    business-specific verbs here.
    """

    PLATFORM_ADMIN = "platform:admin"
    TENANT_MANAGE = "tenant:manage"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    FLEET_READ = "fleet:read"
    FLEET_WRITE = "fleet:write"
    SHIPMENT_READ = "shipment:read"
    SHIPMENT_WRITE = "shipment:write"
    DRIVER_SELF = "driver:self"


# Convenience aggregate: the complete permission set granted to platform admins.
_ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)


# Static role -> permission mapping. frozenset makes each grant immutable and
# cheaply membership-testable. Keyed by the EXISTING UserRole enum.
ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: _ALL_PERMISSIONS,
    UserRole.MANAGER: frozenset(
        {
            Permission.TENANT_MANAGE,
            Permission.USER_READ,
            Permission.USER_WRITE,
            Permission.FLEET_READ,
            Permission.FLEET_WRITE,
            Permission.SHIPMENT_READ,
            Permission.SHIPMENT_WRITE,
        }
    ),
    UserRole.DRIVER: frozenset(
        {
            Permission.DRIVER_SELF,
            Permission.SHIPMENT_READ,
        }
    ),
    UserRole.CLIENT: frozenset(
        {
            Permission.SHIPMENT_READ,
        }
    ),
}


def has_permission(role: UserRole, perm: Permission) -> bool:
    """Return ``True`` if ``role`` is granted ``perm``.

    Unknown or unmapped roles resolve to "no permissions" (deny-by-default)
    and are logged at WARNING level so misconfiguration is visible rather than
    silently permissive.
    """

    granted = ROLE_PERMISSIONS.get(role)
    if granted is None:
        # Defensive: a role that exists in the enum but is absent from the map
        # must never accidentally inherit access.
        logger.warning(
            "Role has no permission mapping; denying by default",
            role=getattr(role, "value", str(role)),
            permission=perm.value,
        )
        return False
    return perm in granted


__all__ = [
    "Permission",
    "ROLE_PERMISSIONS",
    "has_permission",
]
