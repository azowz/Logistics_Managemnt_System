"""Equipment & Asset domain models (context #15, Sprint 6).

Implements the heavy-equipment aggregate (`Equipment`) plus its two tenant-scoped
reference entities (`EquipmentCategory`, `EquipmentModel`) per ADR-008/009 and
`docs/08-heavy-equipment-domain-design.md` Part 1.

Boundary (ADR-009): `Equipment` is the **subject** of a movement (the machine
being transported/rented), distinct from `Vehicle` (Fleet) which performs the
haul. The two are linked by id, never merged.

Tenancy & concurrency follow the platform-wide rules: tenant-isolated via
``tenant_id`` + RLS (ADR-001), optimistic-locked via ``version`` (ADR-004),
soft-deletable + auditable via the shared mixins.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    EquipmentAvailability,
    EquipmentOwnershipType,
    EquipmentStatus,
)


def _enum_values(enum_cls) -> list[str]:
    """Persist enum *values* (e.g. 'active'), not member names ('ACTIVE')."""
    return [member.value for member in enum_cls]


class EquipmentCategory(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """Tenant-scoped equipment taxonomy node (extensible tree)."""

    __tablename__ = "equipment_categories"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "code", name="uq_equipment_categories_tenant_id_code"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class EquipmentModel(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """Catalog entry: a make/model spec template within a category."""

    __tablename__ = "equipment_models"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "code", name="uq_equipment_models_tenant_id_code"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(128))
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    model_year: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(Text)
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Equipment(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """A physical heavy-equipment unit — the subject of a movement (ADR-009)."""

    __tablename__ = "equipment"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "equipment_code", name="uq_equipment_tenant_id_equipment_code"
        ),
        UniqueConstraint(
            "tenant_id", "asset_tag", name="uq_equipment_tenant_id_asset_tag"
        ),
        # Serial uniqueness is optional (serial may be NULL); enforced per tenant
        # for non-null values at the DB level (partial index in the migration).
        CheckConstraint(
            "status IN ('active', 'inactive', 'under_maintenance', 'reserved', "
            "'in_transit', 'decommissioned')",
            name="status",
        ),
        CheckConstraint(
            "availability_status IN ('available', 'reserved', 'unavailable', "
            "'assigned', 'maintenance')",
            name="availability_status",
        ),
        CheckConstraint(
            "ownership_type IN ('owned', 'leased', 'customer_owned', 'third_party')",
            name="ownership_type",
        ),
        CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="weight_non_negative"),
        CheckConstraint("length_m IS NULL OR length_m >= 0", name="length_non_negative"),
        CheckConstraint("width_m IS NULL OR width_m >= 0", name="width_non_negative"),
        CheckConstraint("height_m IS NULL OR height_m >= 0", name="height_non_negative"),
        CheckConstraint("volume_m3 IS NULL OR volume_m3 >= 0", name="volume_non_negative"),
    )

    # --- identity ---
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    equipment_code: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- descriptive ---
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    serial_number: Mapped[Optional[str]] = mapped_column(String(128))
    manufacturer: Mapped[Optional[str]] = mapped_column(String(128))
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    year: Mapped[Optional[int]] = mapped_column(Integer)
    ownership_type: Mapped[EquipmentOwnershipType] = mapped_column(
        SAEnum(
            EquipmentOwnershipType,
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=EquipmentOwnershipType.OWNED,
        server_default="owned",
    )

    # --- lifecycle ---
    status: Mapped[EquipmentStatus] = mapped_column(
        SAEnum(EquipmentStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=EquipmentStatus.ACTIVE,
        server_default="active",
        index=True,
    )
    availability_status: Mapped[EquipmentAvailability] = mapped_column(
        SAEnum(
            EquipmentAvailability,
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=EquipmentAvailability.AVAILABLE,
        server_default="available",
        index=True,
    )

    # --- dimensions / weight ---
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    length_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    width_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    height_m: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    volume_m3: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))

    # --- transport requirement flags ---
    requires_permit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    requires_escort: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    requires_special_handling: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    hazardous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    temperature_sensitive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    insurance_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # --- location ---
    current_warehouse_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    current_location: Mapped[Optional[str]] = mapped_column(String(512))

    # --- metadata ---
    notes: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # --- soft-delete actor + optimistic lock ---
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}

    # Category / model references (read-only convenience relationships).
    category: Mapped["EquipmentCategory"] = relationship(foreign_keys=[category_id])
    model: Mapped[Optional["EquipmentModel"]] = relationship(foreign_keys=[model_id])
