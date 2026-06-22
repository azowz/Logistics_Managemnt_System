"""Shipment aggregate capturing lifecycle, assignment, and metrics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import ShipmentStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User
    from app.models.driver import Driver
    from app.models.vehicle import Vehicle
    from app.models.warehouse import Warehouse
    from app.models.shipment_tracking_event import ShipmentTrackingEvent


class Shipment(TimestampMixin, Base):
    """Core shipment record representing the movement of goods."""

    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("reference_code", name="uq_shipments_reference_code"),
        CheckConstraint("weight_kg > 0", name="ck_shipments_weight_positive"),
        CheckConstraint("volume_m3 > 0", name="ck_shipments_volume_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    reference_code: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    destination_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    driver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drivers.id", ondelete="SET NULL"),
    )
    vehicle_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="SET NULL"),
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        SAEnum(ShipmentStatus, native_enum=False, length=32),
        nullable=False,
        default=ShipmentStatus.CREATED,
    )
    weight_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    volume_m3: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    pickup_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255))

    # Commercial / offer metadata surfaced to drivers (nullable; populated by
    # quoting/dispatch). Added in migration 0002 to back the driver offer feed.
    cargo_type: Mapped[Optional[str]] = mapped_column(String(128))
    price_sar: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    required_vehicle_type: Mapped[Optional[str]] = mapped_column(String(64))

    # Owning client.
    client: Mapped["User"] = relationship(
        back_populates="client_shipments",
        lazy="joined",
        foreign_keys=[client_id],
    )

    # Assigned driver (may be null until assignment).
    driver: Mapped[Optional["Driver"]] = relationship(
        back_populates="shipments",
        foreign_keys=[driver_id],
    )

    # Assigned vehicle (may be null until assignment).
    vehicle: Mapped[Optional["Vehicle"]] = relationship(
        back_populates="shipments",
        foreign_keys=[vehicle_id],
    )

    # Origin warehouse for dispatch.
    origin_warehouse: Mapped["Warehouse"] = relationship(
        back_populates="origin_shipments",
        foreign_keys=[origin_warehouse_id],
    )

    # Destination warehouse for delivery or return.
    destination_warehouse: Mapped["Warehouse"] = relationship(
        back_populates="destination_shipments",
        foreign_keys=[destination_warehouse_id],
    )

    # Append-only tracking history ordered by event_time.
    tracking_events: Mapped[List["ShipmentTrackingEvent"]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="ShipmentTrackingEvent.event_time",
    )
