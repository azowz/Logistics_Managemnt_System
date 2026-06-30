"""Compliance & Permits domain models (context #16, Sprint 7).

Owns the regulatory envelope for heavy/oversize movements: permits, escorts,
route restrictions, axle-weight profiles, compliance checks, and operator
certifications (ADR-008, docs/08 Part 2-4). Compliance owns rule evaluation and
the permit lifecycle; Equipment provides the transport profile; Shipment asks the
dispatch gate whether a movement may proceed — these concerns are NOT merged.

All tables are tenant-scoped (RLS, ADR-001), soft-deletable + auditable, and
optimistic-locked (`version`).
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import AuditMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    ComplianceCheckStatus,
    ComplianceCheckType,
    EscortStatus,
    EscortType,
    OperatorCertificationStatus,
    PermitStatus,
    PermitType,
    RouteRestrictionType,
)


def _enum_values(enum_cls) -> list[str]:
    return [member.value for member in enum_cls]


class Permit(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """A movement permit authorizing an oversize/overweight/special shipment."""

    __tablename__ = "permits"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "permit_number", name="uq_permits_tenant_id_permit_number"
        ),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'under_review', 'approved', "
            "'rejected', 'active', 'expired', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "permit_type IN ('oversize', 'overweight', 'government', 'municipal', "
            "'special_movement', 'site_entry')",
            name="permit_type",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from",
            name="valid_window",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    permit_number: Mapped[str] = mapped_column(String(64), nullable=False)
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    equipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vehicle_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    route_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    permit_type: Mapped[PermitType] = mapped_column(
        SAEnum(PermitType, native_enum=False, length=32, values_callable=_enum_values), nullable=False
    )
    status: Mapped[PermitStatus] = mapped_column(
        SAEnum(PermitStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, default=PermitStatus.DRAFT, server_default="draft", index=True,
    )
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(255))
    region: Mapped[Optional[str]] = mapped_column(String(128))

    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    requires_escort: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    requires_police_escort: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    max_allowed_weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    max_allowed_height: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    max_allowed_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    max_allowed_length: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))

    conditions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(512))

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Escort(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """An escort/pilot plan accompanying an oversize movement."""

    __tablename__ = "escorts"
    __table_args__ = (
        CheckConstraint(
            "escort_type IN ('private_escort', 'police_escort', 'pilot_vehicle', "
            "'technical_support')",
            name="escort_type",
        ),
        CheckConstraint(
            "status IN ('planned', 'scheduled', 'cancelled', 'completed')", name="status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    permit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permits.id", ondelete="SET NULL"), nullable=True, index=True
    )
    escort_type: Mapped[EscortType] = mapped_column(
        SAEnum(EscortType, native_enum=False, length=32, values_callable=_enum_values), nullable=False
    )
    provider_name: Mapped[Optional[str]] = mapped_column(String(255))
    contact_name: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(64))
    start_location: Mapped[Optional[str]] = mapped_column(String(512))
    end_location: Mapped[Optional[str]] = mapped_column(String(512))
    scheduled_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[EscortStatus] = mapped_column(
        SAEnum(EscortStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, default=EscortStatus.PLANNED, server_default="planned", index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class RouteRestriction(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """A geo/attribute road restriction evaluated during dispatch."""

    __tablename__ = "route_restrictions"
    __table_args__ = (
        CheckConstraint(
            "restriction_type IN ('weight_limit', 'height_limit', 'width_limit', "
            "'length_limit', 'time_window', 'hazardous_material', 'road_closure')",
            name="restriction_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    region: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    road_name: Mapped[Optional[str]] = mapped_column(String(255))
    restriction_type: Mapped[RouteRestrictionType] = mapped_column(
        SAEnum(RouteRestrictionType, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, index=True,
    )
    max_weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    max_height: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    max_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    max_length: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class AxleWeightProfile(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """Per equipment+vehicle axle-weight distribution and compliance flag."""

    __tablename__ = "axle_weight_profiles"
    __table_args__ = (
        CheckConstraint("axle_count IS NULL OR axle_count >= 0", name="axle_count_non_negative"),
        CheckConstraint("total_weight IS NULL OR total_weight >= 0", name="total_weight_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    equipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vehicle_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    axle_count: Mapped[Optional[int]] = mapped_column(Integer)
    total_weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    axle_weights: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    max_axle_weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    is_compliant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class ComplianceCheck(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """The result of a single compliance evaluation for a movement."""

    __tablename__ = "compliance_checks"
    __table_args__ = (
        CheckConstraint(
            "check_type IN ('permit_required', 'permit_validity', 'escort_required', "
            "'axle_weight', 'oversize', 'route_restriction', 'operator_certification', "
            "'insurance_required', 'hazardous_material')",
            name="check_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'passed', 'failed', 'warning', 'overridden')", name="status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    equipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True
    )
    vehicle_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    permit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permits.id", ondelete="SET NULL"), nullable=True
    )
    check_type: Mapped[ComplianceCheckType] = mapped_column(
        SAEnum(ComplianceCheckType, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, index=True,
    )
    status: Mapped[ComplianceCheckStatus] = mapped_column(
        SAEnum(ComplianceCheckStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, default=ComplianceCheckStatus.PENDING, server_default="pending", index=True,
    )
    result: Mapped[Optional[str]] = mapped_column(String(512))
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    failure_reasons: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    evaluated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class OperatorCertification(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    """An operator's certification gating eligibility for equipment operations."""

    __tablename__ = "operator_certifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'expired', 'suspended', 'revoked')", name="status"
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from",
            name="valid_window",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipment_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id", ondelete="SET NULL"), nullable=True
    )
    certification_type: Mapped[str] = mapped_column(String(128), nullable=False)
    certification_number: Mapped[Optional[str]] = mapped_column(String(128))
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(255))
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[OperatorCertificationStatus] = mapped_column(
        SAEnum(OperatorCertificationStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, default=OperatorCertificationStatus.ACTIVE, server_default="active", index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}
