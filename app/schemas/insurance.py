"""Pydantic schemas for the Insurance & Claims domain (Sprint 8)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
from app.schemas.common import IdModel, TimestampMixin

_POLICY_SORT = frozenset(
    {"policy_number", "status", "policy_type", "coverage_end_date", "created_at", "updated_at"}
)
_CLAIM_SORT = frozenset(
    {
        "claim_number",
        "status",
        "claim_type",
        "severity",
        "incident_date",
        "created_at",
        "updated_at",
    }
)


def _currency(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.upper()
    if not re.fullmatch(r"[A-Z]{3}", v):
        raise ValueError("currency_code must be a 3-letter ISO-4217 code.")
    return v


def _tz(v: Optional[datetime]) -> Optional[datetime]:
    if v is not None and v.tzinfo is None:
        raise ValueError("Datetime fields must be timezone-aware (UTC).")
    return v


# --- Insurance policy ------------------------------------------------------


class InsurancePolicyCreate(BaseModel):
    policy_number: Optional[str] = Field(default=None, max_length=64)
    provider_name: Optional[str] = Field(default=None, max_length=255)
    policy_type: InsurancePolicyType
    coverage_start_date: Optional[datetime] = None
    coverage_end_date: Optional[datetime] = None
    coverage_amount: Optional[Decimal] = Field(default=None, ge=0)
    deductible_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    covers_equipment: bool = False
    covers_shipment: bool = False
    covers_third_party: bool = False
    covers_hazardous_cargo: bool = False
    terms: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @field_validator("coverage_start_date", "coverage_end_date")
    @classmethod
    def tz(cls, v):
        return _tz(v)

    @model_validator(mode="after")
    def window(self) -> "InsurancePolicyCreate":
        if (
            self.coverage_start_date
            and self.coverage_end_date
            and self.coverage_end_date < self.coverage_start_date
        ):
            raise ValueError("coverage_end_date must not be earlier than coverage_start_date.")
        return self


class InsurancePolicyUpdate(BaseModel):
    provider_name: Optional[str] = Field(default=None, max_length=255)
    coverage_start_date: Optional[datetime] = None
    coverage_end_date: Optional[datetime] = None
    coverage_amount: Optional[Decimal] = Field(default=None, ge=0)
    deductible_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    covers_equipment: Optional[bool] = None
    covers_shipment: Optional[bool] = None
    covers_third_party: Optional[bool] = None
    covers_hazardous_cargo: Optional[bool] = None
    terms: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @model_validator(mode="after")
    def at_least_one(self) -> "InsurancePolicyUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class InsurancePolicyRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    policy_number: str
    provider_name: Optional[str] = None
    policy_type: InsurancePolicyType
    status: InsurancePolicyStatus
    coverage_start_date: Optional[datetime] = None
    coverage_end_date: Optional[datetime] = None
    coverage_amount: Optional[Decimal] = None
    deductible_amount: Optional[Decimal] = None
    currency_code: str
    covers_equipment: bool
    covers_shipment: bool
    covers_third_party: bool
    covers_hazardous_cargo: bool
    terms: Optional[dict] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class InsurancePolicyListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    status: Optional[InsurancePolicyStatus] = None
    policy_type: Optional[InsurancePolicyType] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _POLICY_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_POLICY_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


# --- Coverage rule ---------------------------------------------------------


class CoverageRuleCreate(BaseModel):
    policy_id: uuid.UUID
    coverage_type: CoverageType
    cargo_type: Optional[str] = Field(default=None, max_length=128)
    equipment_category_id: Optional[uuid.UUID] = None
    max_coverage_amount: Optional[Decimal] = Field(default=None, ge=0)
    deductible_amount: Optional[Decimal] = Field(default=None, ge=0)
    requires_compliance_clearance: bool = False
    exclusions: Optional[dict] = None
    active: bool = True
    notes: Optional[str] = Field(default=None, max_length=4000)


class CoverageRuleUpdate(BaseModel):
    cargo_type: Optional[str] = Field(default=None, max_length=128)
    equipment_category_id: Optional[uuid.UUID] = None
    max_coverage_amount: Optional[Decimal] = Field(default=None, ge=0)
    deductible_amount: Optional[Decimal] = Field(default=None, ge=0)
    requires_compliance_clearance: Optional[bool] = None
    exclusions: Optional[dict] = None
    active: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def at_least_one(self) -> "CoverageRuleUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class CoverageRuleRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    policy_id: uuid.UUID
    coverage_type: CoverageType
    cargo_type: Optional[str] = None
    equipment_category_id: Optional[uuid.UUID] = None
    max_coverage_amount: Optional[Decimal] = None
    deductible_amount: Optional[Decimal] = None
    requires_compliance_clearance: bool
    exclusions: Optional[dict] = None
    active: bool
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


# --- Claim -----------------------------------------------------------------


class ClaimCreate(BaseModel):
    claim_number: Optional[str] = Field(default=None, max_length=64)
    policy_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    compliance_check_id: Optional[uuid.UUID] = None
    permit_id: Optional[uuid.UUID] = None
    claim_type: ClaimType
    severity: ClaimSeverity = ClaimSeverity.MEDIUM
    incident_date: Optional[datetime] = None
    claimed_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    description: Optional[str] = Field(default=None, max_length=4000)
    evidence: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @field_validator("incident_date")
    @classmethod
    def tz(cls, v):
        return _tz(v)


class ClaimUpdate(BaseModel):
    severity: Optional[ClaimSeverity] = None
    incident_date: Optional[datetime] = None
    claimed_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    description: Optional[str] = Field(default=None, max_length=4000)
    evidence: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)

    @model_validator(mode="after")
    def at_least_one(self) -> "ClaimUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class ClaimApprovalRequest(BaseModel):
    approved_amount: Decimal = Field(ge=0)
    allow_override: bool = False


class ClaimRejectionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class ClaimSettlementRequest(BaseModel):
    settlement_notes: str = Field(min_length=1, max_length=4000)


class ClaimStatusRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=512)


class ClaimRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    claim_number: str
    policy_id: Optional[uuid.UUID] = None
    shipment_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    compliance_check_id: Optional[uuid.UUID] = None
    permit_id: Optional[uuid.UUID] = None
    claim_type: ClaimType
    status: ClaimStatus
    severity: ClaimSeverity
    incident_date: Optional[datetime] = None
    reported_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    reopened_at: Optional[datetime] = None
    claimed_amount: Optional[Decimal] = None
    approved_amount: Optional[Decimal] = None
    currency_code: str
    description: Optional[str] = None
    rejection_reason: Optional[str] = None
    settlement_notes: Optional[str] = None
    evidence: Optional[dict] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[uuid.UUID] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class ClaimListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    status: Optional[ClaimStatus] = None
    claim_type: Optional[ClaimType] = None
    shipment_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    policy_id: Optional[uuid.UUID] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _CLAIM_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_CLAIM_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


# --- Damage report / liability ---------------------------------------------


class DamageReportCreate(BaseModel):
    shipment_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    damage_type: DamageType
    severity: ClaimSeverity = ClaimSeverity.MEDIUM
    description: Optional[str] = Field(default=None, max_length=4000)
    estimated_cost: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    photos: Optional[List[Any]] = None
    evidence: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)


class DamageReportRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    claim_id: uuid.UUID
    shipment_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    damage_type: DamageType
    severity: ClaimSeverity
    description: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    currency_code: str
    photos: Optional[List[Any]] = None
    evidence: Optional[dict] = None
    reported_by: Optional[uuid.UUID] = None
    reported_at: Optional[datetime] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class LiabilityRecordCreate(BaseModel):
    responsible_party_type: ResponsiblePartyType
    responsible_party_id: Optional[uuid.UUID] = None
    liability_percentage: Optional[Decimal] = Field(default=None, ge=0, le=100)
    liability_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    determination_reason: Optional[str] = Field(default=None, max_length=4000)
    allow_override: bool = False
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("currency_code")
    @classmethod
    def cur(cls, v):
        return _currency(v)


class LiabilityRecordRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    claim_id: uuid.UUID
    responsible_party_type: ResponsiblePartyType
    responsible_party_id: Optional[uuid.UUID] = None
    liability_percentage: Optional[Decimal] = None
    liability_amount: Optional[Decimal] = None
    currency_code: str
    determination_reason: Optional[str] = None
    determined_by: Optional[uuid.UUID] = None
    determined_at: Optional[datetime] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)
