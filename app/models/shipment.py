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
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import ShipmentPriority, ShipmentStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User
    from app.models.driver import Driver
    from app.models.order import Order
    from app.models.vehicle import Vehicle
    from app.models.warehouse import Warehouse
    from app.models.shipment_tracking_event import ShipmentTrackingEvent


def _enum_values(enum_cls) -> list[str]:
    """Persist enum *values* (e.g. 'normal'), not member names ('NORMAL')."""
    return [member.value for member in enum_cls]


class Shipment(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """Core shipment record representing the movement of goods."""

    __tablename__ = "shipments"
    __table_args__ = (
        # Reference code is unique PER TENANT (ADR-001 / docs/03 §3.2).
        UniqueConstraint(
            "tenant_id", "reference_code", name="uq_shipments_tenant_id_reference_code"
        ),
        # Short logical names: the metadata ``ck`` naming convention expands these
        # to ``ck_shipments_<name>`` (matching the migration-authored DB names).
        CheckConstraint("weight_kg > 0", name="weight_positive"),
        CheckConstraint("volume_m3 > 0", name="volume_positive"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')", name="priority"
        ),
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
    reference_code: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Optional upstream order this shipment fulfils (Sprint 5). Nullable so
    # shipments created outside the order flow (e.g. ad-hoc dispatch) still work.
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
        index=True,
    )
    # Operational priority for dispatch ordering (Sprint 5). Stored lowercase.
    priority: Mapped[ShipmentPriority] = mapped_column(
        SAEnum(
            ShipmentPriority,
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=ShipmentPriority.NORMAL,
        server_default="normal",
        index=True,
    )
    weight_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    volume_m3: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    pickup_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255))
    return_reason: Mapped[Optional[str]] = mapped_column(String(255))

    # Optional equipment reference (Sprint 5). The Equipment aggregate landed in
    # Sprint 6 (context #15, ADR-009); the FK constraint is added by migration
    # 0009 (PostgreSQL) and validated in ShipmentService for every dialect.
    equipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Commercial / offer metadata surfaced to drivers (nullable; populated by
    # quoting/dispatch). Added in migration 0002 to back the driver offer feed.
    cargo_type: Mapped[Optional[str]] = mapped_column(String(128))
    cargo_description: Mapped[Optional[str]] = mapped_column(Text)
    price_sar: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    # ISO-4217 currency for the price; defaults to SAR for existing rows
    # (docs/03 §0 multi-market readiness).
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    required_vehicle_type: Mapped[Optional[str]] = mapped_column(String(64))

    # Soft-delete actor attribution beyond SoftDeleteMixin (Sprint 5).
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Optimistic concurrency (ADR-004 / docs/03 §0).
    __mapper_args__ = {"version_id_col": version}

    # Optional upstream order (Sprint 5).
    order: Mapped[Optional["Order"]] = relationship(
        foreign_keys=[order_id],
    )

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
