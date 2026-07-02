"""User account model with role-based access control."""

from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Enum as SAEnum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:  # pragma: no cover - used for type checking only
    from app.models.driver import Driver
    from app.models.shipment import Shipment
    from app.models.shipment_tracking_event import ShipmentTrackingEvent


class User(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """Authenticated system user with a single role."""

    __tablename__ = "users"
    # Email is unique PER TENANT (ADR-001 / docs/03 §3.2), not globally.
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_id_email"),)

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
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Optimistic concurrency: SQLAlchemy guards every UPDATE with this version and
    # increments it; concurrent writers raise StaleDataError (ADR-004 / docs/03 §0).
    __mapper_args__ = {"version_id_col": version}
    email: Mapped[str] = mapped_column(
        String(255),
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
