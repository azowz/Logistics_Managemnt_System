"""Vehicle model describing transport assets and their capacity."""

from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Enum as SAEnum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import VehicleStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.warehouse import Warehouse
    from app.models.shipment import Shipment


class Vehicle(TimestampMixin, Base):
    """Transport vehicle with load limits and operational status."""

    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("plate_number", name="uq_vehicles_plate_number"),
        UniqueConstraint("vin", name="uq_vehicles_vin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    plate_number: Mapped[str] = mapped_column(String(32), nullable=False)
    vin: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[VehicleStatus] = mapped_column(
        SAEnum(VehicleStatus, native_enum=False, length=32),
        nullable=False,
        default=VehicleStatus.ACTIVE,
    )
    capacity_weight_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    capacity_volume_m3: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    home_warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="SET NULL"),
    )

    # Warehouse where the vehicle is usually stationed.
    home_warehouse: Mapped[Optional["Warehouse"]] = relationship(
        back_populates="vehicles",
    )

    # Shipments that have been assigned to this vehicle.
    shipments: Mapped[List["Shipment"]] = relationship(
        back_populates="vehicle",
    )
