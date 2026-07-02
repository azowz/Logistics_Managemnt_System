"""Order aggregate — a transport order placed by a customer.

An Order is the commercial request to move cargo from a pickup location to a
delivery location. It owns a lifecycle state machine (see
:class:`app.services.order_policies.OrderStateMachine`) and is the upstream
aggregate that dispatch/fulfilment is driven from.

Tenancy & concurrency follow the platform-wide rules:
  * tenant-isolated via ``tenant_id`` + Row-Level Security (ADR-001),
  * optimistic-locked via ``version`` (ADR-004),
  * soft-deletable + auditable via the shared mixins.

Business invariants enforced at the DB layer:
  * ``order_number`` is unique per tenant (``uq_orders_tenant_id_order_number``).
  * ``status`` ∈ {draft, submitted, approved, scheduled, assigned, in_transit,
    delivered, cancelled, failed}.
  * ``order_type`` / ``order_source`` / ``priority`` are constrained to their enums.
  * ``cargo_weight_kg`` / ``cargo_volume_m3`` / ``distance_km`` are non-negative.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import OrderPriority, OrderSource, OrderStatus, OrderType


def _enum_values(enum_cls) -> list[str]:
    """Persist enum *values* (e.g. 'draft'), not member names ('DRAFT').

    SQLAlchemy's ``Enum`` stores member names by default; our CHECK constraints,
    migrations, and API contract all use the lowercase values, so every
    ``SAEnum`` column must opt into ``values_callable``.
    """
    return [member.value for member in enum_cls]


class Order(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """A customer's transport order within a tenant."""

    __tablename__ = "orders"
    __table_args__ = (
        # Order number is unique PER TENANT (ADR-001).
        UniqueConstraint("tenant_id", "order_number", name="uq_orders_tenant_id_order_number"),
        # Short logical names — the ``ck`` naming convention expands these to
        # ``ck_orders_<name>`` (matching the migration-authored DB names).
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'scheduled', "
            "'assigned', 'in_transit', 'delivered', 'cancelled', 'failed')",
            name="status",
        ),
        CheckConstraint(
            "order_type IN ('standard', 'express', 'same_day', 'economy', 'return')",
            name="order_type",
        ),
        CheckConstraint(
            "order_source IN ('web', 'mobile', 'api', 'phone', 'email', 'walk_in')",
            name="order_source",
        ),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="priority"),
        CheckConstraint(
            "cargo_weight_kg IS NULL OR cargo_weight_kg >= 0",
            name="cargo_weight_non_negative",
        ),
        CheckConstraint(
            "cargo_volume_m3 IS NULL OR cargo_volume_m3 >= 0",
            name="cargo_volume_non_negative",
        ),
        CheckConstraint("distance_km IS NULL OR distance_km >= 0", name="distance_non_negative"),
    )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

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
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Human-facing identifier, unique within a tenant (auto-generated if omitted).
    order_number: Mapped[str] = mapped_column(String(64), nullable=False)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    order_type: Mapped[OrderType] = mapped_column(
        SAEnum(OrderType, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=OrderType.STANDARD,
    )
    order_source: Mapped[OrderSource] = mapped_column(
        SAEnum(OrderSource, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=OrderSource.WEB,
    )
    priority: Mapped[OrderPriority] = mapped_column(
        SAEnum(OrderPriority, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=OrderPriority.NORMAL,
        index=True,
    )

    # ------------------------------------------------------------------
    # Lifecycle state
    # ------------------------------------------------------------------

    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=OrderStatus.DRAFT,
        index=True,
    )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    requested_pickup_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    requested_delivery_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------

    pickup_location: Mapped[Optional[str]] = mapped_column(Text)
    delivery_location: Mapped[Optional[str]] = mapped_column(Text)
    pickup_latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    pickup_longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    delivery_latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    delivery_longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))

    # Routing metrics (nullable; populated by routing/quoting).
    distance_km: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    estimated_duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)

    # ------------------------------------------------------------------
    # Cargo
    # ------------------------------------------------------------------

    cargo_description: Mapped[Optional[str]] = mapped_column(Text)
    cargo_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    cargo_volume_m3: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    dangerous_goods: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    temperature_requirements: Mapped[Optional[str]] = mapped_column(String(128))
    is_fragile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    insurance_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    special_instructions: Mapped[Optional[str]] = mapped_column(Text)

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    assigned_dispatcher_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Lifecycle timestamps / reasons (populated by state transitions)
    # ------------------------------------------------------------------

    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(512))
    failure_reason: Mapped[Optional[str]] = mapped_column(String(512))

    # ------------------------------------------------------------------
    # Soft-delete extension (actor attribution beyond SoftDeleteMixin)
    # ------------------------------------------------------------------

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )

    # ------------------------------------------------------------------
    # Optimistic concurrency (ADR-004)
    # ------------------------------------------------------------------

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}
