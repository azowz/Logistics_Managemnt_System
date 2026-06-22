"""Shared ORM mixins used across multiple models.

``TimestampMixin`` is preserved verbatim for backwards compatibility with the
existing models that already depend on it. The additional mixins below
(``SoftDeleteMixin``, ``AuditMixin``, ``TenantMixin``) are opt-in cross-cutting
concerns intended primarily for FUTURE models built on
:class:`app.db.base_model.BaseModel`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.datetime import utcnow


class TimestampMixin:
    """Adds immutable creation and mutable update timestamps in UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds soft-delete semantics via a nullable ``deleted_at`` timestamp.

    A row is considered "deleted" when ``deleted_at`` is set. This lets queries
    filter out logically removed rows while retaining the data for audit and
    recovery. Callers are responsible for adding ``WHERE deleted_at IS NULL``
    predicates (or a global query filter) where appropriate.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        """Return ``True`` when the row has been soft-deleted."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark the row as deleted using a timezone-aware UTC timestamp.

        Idempotent: re-invoking does not overwrite the original deletion time,
        preserving the first-deletion audit point.
        """
        if self.deleted_at is None:
            self.deleted_at = utcnow()

    def restore(self) -> None:
        """Clear the soft-delete marker, making the row active again."""
        self.deleted_at = None


class AuditMixin:
    """Tracks which user created and last updated a row.

    Both columns are nullable because system-initiated writes (migrations,
    background jobs, seed data) may have no associated user. Application code is
    responsible for populating these from the authenticated principal.
    """

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        default=None,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        default=None,
    )


class TenantMixin:
    """Associates a row with a tenant for multi-tenant isolation.

    ``tenant_id`` is NOT NULL and indexed because nearly every tenant-scoped
    query filters on it; the index keeps those lookups efficient. Pair this
    with Row-Level Security and :func:`app.db.tenant.apply_tenant_guc` for
    defense-in-depth isolation at the database layer.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )


__all__ = [
    "TimestampMixin",
    "SoftDeleteMixin",
    "AuditMixin",
    "TenantMixin",
]
