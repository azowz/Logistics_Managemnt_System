"""Driver operational profile linked to a user with role=driver."""

from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User
    from app.models.warehouse import Warehouse
    from app.models.shipment import Shipment


class Driver(TimestampMixin, Base):
    """Operational driver profile and eligibility data."""

    __tablename__ = "drivers"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_drivers_user_id"),
        UniqueConstraint("license_number", name="uq_drivers_license_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
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
