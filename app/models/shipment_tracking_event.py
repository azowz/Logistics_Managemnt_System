"""Immutable tracking events associated with a shipment."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import ShipmentStatus, TrackingEventType

if TYPE_CHECKING:  # pragma: no cover
    from app.models.shipment import Shipment
    from app.models.user import User


class ShipmentTrackingEvent(TimestampMixin, Base):
    """Append-only event describing shipment status or location change."""

    __tablename__ = "shipment_tracking_events"

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
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[TrackingEventType] = mapped_column(
        SAEnum(TrackingEventType, native_enum=False, length=32),
        nullable=False,
    )
    status: Mapped[Optional[ShipmentStatus]] = mapped_column(
        SAEnum(ShipmentStatus, native_enum=False, length=32),
        nullable=True,
    )
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6))
    notes: Mapped[Optional[str]] = mapped_column(Text())
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    evidence_url: Mapped[Optional[str]] = mapped_column(String(512))

    # Parent shipment; delete cascades to events to keep history scoped.
    shipment: Mapped["Shipment"] = relationship(
        back_populates="tracking_events",
        foreign_keys=[shipment_id],
    )

    # User who recorded the event (driver or manager).
    recorded_by: Mapped[Optional["User"]] = relationship(
        back_populates="recorded_events",
        foreign_keys=[recorded_by_user_id],
    )
