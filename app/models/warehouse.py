"""Warehouse definition with capacity constraints and location metadata."""

from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.vehicle import Vehicle
    from app.models.driver import Driver
    from app.models.shipment import Shipment


class Warehouse(TimestampMixin, Base):
    """Physical warehouse with capacity controls and geolocation."""

    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("code", name="uq_warehouses_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[Optional[str]] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(128), nullable=False)
    postal_code: Mapped[Optional[str]] = mapped_column(String(32))
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6))
    capacity_weight_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    capacity_volume_m3: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    max_daily_shipments: Mapped[Optional[int]] = mapped_column()

    # Vehicles based at this warehouse.
    vehicles: Mapped[List["Vehicle"]] = relationship(
        back_populates="home_warehouse",
    )

    # Drivers primarily dispatched from this warehouse.
    drivers: Mapped[List["Driver"]] = relationship(
        back_populates="home_warehouse",
    )

    # Shipments originating from this warehouse.
    origin_shipments: Mapped[List["Shipment"]] = relationship(
        back_populates="origin_warehouse",
        foreign_keys="Shipment.origin_warehouse_id",
    )

    # Shipments destined for this warehouse (returns or inbound staging).
    destination_shipments: Mapped[List["Shipment"]] = relationship(
        back_populates="destination_warehouse",
        foreign_keys="Shipment.destination_warehouse_id",
    )
