"""Tenant aggregate — the isolation boundary for the multi-tenant platform.

Phase 5 milestone M1 (ADR-001 / docs/03 §8). Every other aggregate carries a
``tenant_id`` foreign key to this table and is filtered by Row-Level Security.
The *platform* org is the nil-UUID tenant (:data:`app.db.tenant.PLATFORM_TENANT_ID`,
"tenant 0"), seeded by migration ``0003`` and used for cross-tenant / admin
operations.

This model deliberately mirrors the existing core models' style (own ``uuid4``
primary key + :class:`~app.db.mixins.TimestampMixin`) rather than the UUIDv7
:class:`~app.db.base_model.BaseModel`: ``tenants`` is a low-churn reference
table (ADR-007 allows UUIDv4 there) and the platform row uses a fixed id.
``tenants`` is the tenant boundary itself, so it does NOT carry ``tenant_id``.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin

# Allowed values for the VARCHAR+CHECK status / isolation columns (ADR-001).
_TENANT_STATUSES = ("active", "suspended")
_ISOLATION_MODES = ("shared", "dedicated")


class Tenant(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """A customer organization (or the platform org) on the shared schema."""

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
        # Short logical names: the ``ck`` naming convention expands these to
        # ``ck_tenants_<name>`` (matching the migration-authored DB names).
        CheckConstraint("status IN ('active', 'suspended')", name="status"),
        CheckConstraint(
            "isolation_mode IN ('shared', 'dedicated')", name="isolation_mode"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    # Globally-unique, human-readable handle (not tenant-scoped).
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
    )
    # Hybrid escape hatch (ADR-001): a regulated tenant can be routed to its own
    # schema/database without app changes by flipping this to 'dedicated'.
    isolation_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="shared",
    )
    # Data-residency hint; sharding by region is a later-stage option.
    region: Mapped[Optional[str]] = mapped_column(String(64))
    settings: Mapped[Optional[dict]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Optimistic concurrency (ADR-004 / docs/03 §0).
    __mapper_args__ = {"version_id_col": version}

    @property
    def is_platform(self) -> bool:
        """Return ``True`` for the nil-UUID platform tenant ("tenant 0")."""
        return self.id == uuid.UUID("00000000-0000-0000-0000-000000000000")
