"""Driver operational profile linked to a user with role=driver."""

from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User
    from app.models.warehouse import Warehouse
    from app.models.shipment import Shipment


class Driver(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """Operational driver profile and eligibility data."""

    __tablename__ = "drivers"
    # Driver natural keys are unique PER TENANT (ADR-001 / docs/03 §3.2).
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_drivers_tenant_id_user_id"),
        UniqueConstraint("tenant_id", "license_number", name="uq_drivers_tenant_id_license_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    license_number: Mapped[str] = mapped_column(String(64), nullable=False)
    license_class: Mapped[Optional[str]] = mapped_column(String(32))
    phone_number: Mapped[Optional[str]] = mapped_column(String(32))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    home_warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="SET NULL"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Optimistic concurrency (ADR-004 / docs/03 §0).
    __mapper_args__ = {"version_id_col": version}

    # User owning this driver profile.
    user: Mapped["User"] = relationship(
        back_populates="driver",
        lazy="joined",
    )

    # Preferred home warehouse for dispatching.
    home_warehouse: Mapped[Optional["Warehouse"]] = relationship(
        back_populates="drivers",
    )

    # Shipments assigned to this driver across their lifecycle.
    shipments: Mapped[List["Shipment"]] = relationship(
        back_populates="driver",
    )
