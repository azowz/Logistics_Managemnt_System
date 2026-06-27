"""Repository encapsulating tenant persistence operations.

Tenant management is a *platform* operation (it runs under the nil-UUID platform
scope), so these queries are intentionally not tenant-filtered. ``tenants`` is
the isolation boundary itself and carries no ``tenant_id``.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant


class TenantRepository:
    """Provides tenant retrieval and lifecycle persistence helpers."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, tenant_id: str | uuid.UUID) -> Optional[Tenant]:
        """Return a tenant by primary key, or ``None`` if not found / malformed."""
        try:
            tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
        except ValueError:
            return None
        return self._session.scalars(select(Tenant).where(Tenant.id == tid)).first()

    def get_by_slug(self, slug: str) -> Optional[Tenant]:
        """Return a tenant by its globally-unique slug, or ``None``."""
        return self._session.scalars(select(Tenant).where(Tenant.slug == slug)).first()

    def add(self, tenant: Tenant) -> Tenant:
        """Persist a new tenant within the caller's unit of work (no commit)."""
        self._session.add(tenant)
        self._session.flush()
        return tenant
