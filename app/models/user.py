"""User account model with role-based access control."""

from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Enum as SAEnum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:  # pragma: no cover - used for type checking only
    from app.models.driver import Driver
    from app.models.shipment import Shipment
    from app.models.shipment_tracking_event import ShipmentTrackingEvent


class User(TimestampMixin, Base):
    """Authenticated system user with a single role."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, length=32),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # One-to-one driver profile for users with role=driver.
    driver: Mapped[Optional["Driver"]] = relationship(
        back_populates="user",
        uselist=False,
    )

    # Client ownership of shipments; shipments persist even if client is deactivated.
    client_shipments: Mapped[List["Shipment"]] = relationship(
        back_populates="client",
        foreign_keys="Shipment.client_id",
    )

    # Tracking events recorded by this user (drivers or managers).
    recorded_events: Mapped[List["ShipmentTrackingEvent"]] = relationship(
        back_populates="recorded_by",
        foreign_keys="ShipmentTrackingEvent.recorded_by_user_id",
    )
