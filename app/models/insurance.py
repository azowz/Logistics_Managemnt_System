"""Insurance & Claims domain models (context #17, Sprint 8).

Owns insurance policies, coverage rules, the claim workflow, damage reports, and
liability records for high-value equipment/shipment movements (ADR-008, docs/08
Part 5). Claims may reference Shipment / Order / Customer / Equipment / Compliance
by id, but Insurance & Claims owns the claim lifecycle. Billing consumes approved
outcomes later; it does not own the lifecycle.

All tables are tenant-scoped (RLS), soft-deletable + auditable, optimistic-locked.
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
    ClaimSeverity,
    ClaimStatus,
    ClaimType,
    CoverageType,
    DamageType,
    InsurancePolicyStatus,
    InsurancePolicyType,
    ResponsiblePartyType,
)


def _enum_values(enum_cls) -> list[str]:
    return [member.value for member in enum_cls]


class InsurancePolicy(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "insurance_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "policy_number", name="uq_insurance_policies_tenant_id_policy_number"),
        CheckConstraint(
            "status IN ('draft', 'active', 'suspended', 'expired', 'cancelled')", name="status"
        ),
        CheckConstraint(
            "policy_type IN ('cargo', 'equipment_in_transit', 'third_party_liability', "
            "'project_car_ear', 'marine_inland')",
            name="policy_type",
        ),
        CheckConstraint("coverage_amount IS NULL OR coverage_amount >= 0", name="coverage_amount_non_negative"),
        CheckConstraint("deductible_amount IS NULL OR deductible_amount >= 0", name="deductible_non_negative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
        CheckConstraint(
            "coverage_start_date IS NULL OR coverage_end_date IS NULL OR coverage_end_date >= coverage_start_date",
            name="coverage_window",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    policy_number: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[Optional[str]] = mapped_column(String(255))
    policy_type: Mapped[InsurancePolicyType] = mapped_column(
        SAEnum(InsurancePolicyType, native_enum=False, length=32, values_callable=_enum_values), nullable=False
    )
    status: Mapped[InsurancePolicyStatus] = mapped_column(
        SAEnum(InsurancePolicyStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, default=InsurancePolicyStatus.DRAFT, server_default="draft", index=True,
    )
    coverage_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    coverage_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    coverage_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    deductible_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    covers_equipment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    covers_shipment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    covers_third_party: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    covers_hazardous_cargo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    terms: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class CoverageRule(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "coverage_rules"
    __table_args__ = (
        CheckConstraint(
            "coverage_type IN ('shipment_loss', 'shipment_damage', 'equipment_damage', "
            "'third_party_liability', 'delay_penalty', 'hazardous_cargo')",
            name="coverage_type",
        ),
        CheckConstraint("max_coverage_amount IS NULL OR max_coverage_amount >= 0", name="max_coverage_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coverage_type: Mapped[CoverageType] = mapped_column(
        SAEnum(CoverageType, native_enum=False, length=32, values_callable=_enum_values), nullable=False
    )
    cargo_type: Mapped[Optional[str]] = mapped_column(String(128))
    equipment_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id", ondelete="SET NULL"), nullable=True
    )
    max_coverage_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    deductible_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    requires_compliance_clearance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    exclusions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class Claim(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "claim_number", name="uq_claims_tenant_id_claim_number"),
        CheckConstraint(
            "status IN ('created', 'under_review', 'approved', 'rejected', 'settled', 'closed')",
            name="status",
        ),
        CheckConstraint(
            "claim_type IN ('shipment_loss', 'shipment_damage', 'equipment_damage', "
            "'delay_claim', 'third_party_liability', 'compliance_violation')",
            name="claim_type",
        ),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity"),
        CheckConstraint("claimed_amount IS NULL OR claimed_amount >= 0", name="claimed_amount_non_negative"),
        CheckConstraint("approved_amount IS NULL OR approved_amount >= 0", name="approved_amount_non_negative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_number: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("insurance_policies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    equipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True, index=True
    )
    compliance_check_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_checks.id", ondelete="SET NULL"), nullable=True
    )
    permit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permits.id", ondelete="SET NULL"), nullable=True
    )
    claim_type: Mapped[ClaimType] = mapped_column(
        SAEnum(ClaimType, native_enum=False, length=32, values_callable=_enum_values), nullable=False
    )
    status: Mapped[ClaimStatus] = mapped_column(
        SAEnum(ClaimStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, default=ClaimStatus.CREATED, server_default="created", index=True,
    )
    severity: Mapped[ClaimSeverity] = mapped_column(
        SAEnum(ClaimSeverity, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, default=ClaimSeverity.MEDIUM, server_default="medium",
    )
    incident_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reopened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    claimed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    approved_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    description: Mapped[Optional[str]] = mapped_column(Text)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(512))
    settlement_notes: Mapped[Optional[str]] = mapped_column(Text)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class DamageReport(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "damage_reports"
    __table_args__ = (
        CheckConstraint(
            "damage_type IN ('cargo_damage', 'equipment_damage', 'vehicle_damage', "
            "'property_damage', 'missing_items', 'delay_damage')",
            name="damage_type",
        ),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity"),
        CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="estimated_cost_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    equipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True
    )
    damage_type: Mapped[DamageType] = mapped_column(
        SAEnum(DamageType, native_enum=False, length=32, values_callable=_enum_values), nullable=False
    )
    severity: Mapped[ClaimSeverity] = mapped_column(
        SAEnum(ClaimSeverity, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False, default=ClaimSeverity.MEDIUM, server_default="medium",
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    estimated_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    photos: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    reported_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    reported_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}


class LiabilityRecord(TimestampMixin, AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "liability_records"
    __table_args__ = (
        CheckConstraint(
            "responsible_party_type IN ('customer', 'carrier', 'driver', 'company', "
            "'third_party', 'unknown')",
            name="responsible_party_type",
        ),
        CheckConstraint(
            "liability_percentage IS NULL OR (liability_percentage >= 0 AND liability_percentage <= 100)",
            name="liability_percentage_range",
        ),
        CheckConstraint("liability_amount IS NULL OR liability_amount >= 0", name="liability_amount_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    responsible_party_type: Mapped[ResponsiblePartyType] = mapped_column(
        SAEnum(ResponsiblePartyType, native_enum=False, length=32, values_callable=_enum_values), nullable=False
    )
    responsible_party_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    liability_percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    liability_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="SAR")
    determination_reason: Mapped[Optional[str]] = mapped_column(Text)
    determined_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    determined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __mapper_args__ = {"version_id_col": version}
