"""Tenant provisioning / lifecycle application service (ADR-001, milestone M1).

Provisioning and suspension are **platform** operations and must run under the
nil-UUID platform scope (e.g. via ``session_scope(PLATFORM_TENANT_ID)`` or an
authenticated platform-admin request) so the writes are permitted by the
RLS platform policy branch.

This service owns the unit of work (one transaction per command). It does not
import HTTP/FastAPI types (Clean Architecture, docs/05 §3).
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.repositories.tenant_repository import TenantRepository
from app.services.exceptions import ConflictError, NotFoundError, ValidationError

_VALID_STATUSES = {"active", "suspended"}
_VALID_ISOLATION = {"shared", "dedicated"}


class TenantService:
    """Create and manage tenant lifecycle (provision, suspend, reactivate)."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = TenantRepository(session)

    def provision(
        self,
        *,
        slug: str,
        name: str,
        region: Optional[str] = None,
        isolation_mode: str = "shared",
        settings: Optional[dict] = None,
    ) -> Tenant:
        """Create a new active tenant; slug must be globally unique.

        Raises :class:`ValidationError` on bad input and :class:`ConflictError`
        when the slug is already taken.
        """
        slug_norm = (slug or "").strip().lower()
        if not slug_norm:
            raise ValidationError("Tenant slug is required.")
        if isolation_mode not in _VALID_ISOLATION:
            raise ValidationError(f"Invalid isolation_mode: {isolation_mode!r}.")
        if not (name or "").strip():
            raise ValidationError("Tenant name is required.")
        if self._repo.get_by_slug(slug_norm) is not None:
            raise ConflictError(f"Tenant slug already exists: {slug_norm!r}.")

        tenant = Tenant(
            slug=slug_norm,
            name=name.strip(),
            status="active",
            isolation_mode=isolation_mode,
            region=region,
            settings=settings,
        )
        self._repo.add(tenant)
        self._session.commit()
        self._session.refresh(tenant)
        return tenant

    def set_status(self, tenant_id: str | uuid.UUID, status: str) -> Tenant:
        """Transition a tenant between ``active`` and ``suspended``."""
        if status not in _VALID_STATUSES:
            raise ValidationError(f"Invalid tenant status: {status!r}.")
        tenant = self._repo.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError("Tenant not found.")
        tenant.status = status
        self._session.commit()
        self._session.refresh(tenant)
        return tenant

    def suspend(self, tenant_id: str | uuid.UUID) -> Tenant:
        """Suspend a tenant (blocks new work; data retained)."""
        return self.set_status(tenant_id, "suspended")

    def reactivate(self, tenant_id: str | uuid.UUID) -> Tenant:
        """Reactivate a previously suspended tenant."""
        return self.set_status(tenant_id, "active")
