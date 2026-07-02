"""Pydantic schemas for the Compliance & Permits domain (Sprint 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
from app.schemas.common import IdModel, TimestampMixin

_PERMIT_SORT = frozenset(
    {"permit_number", "status", "permit_type", "valid_until", "created_at", "updated_at"}
)
_CHECK_SORT = frozenset({"check_type", "status", "created_at", "updated_at"})
_ESCORT_SORT = frozenset({"status", "scheduled_start", "created_at", "updated_at"})


def _require_tz(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        raise ValueError("Datetime fields must be timezone-aware (UTC).")
    return value


# --- Permit ----------------------------------------------------------------


class PermitCreate(BaseModel):
    permit_number: Optional[str] = Field(default=None, max_length=64)
    permit_type: PermitType
    shipment_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    vehicle_id: Optional[uuid.UUID] = None
    route_id: Optional[uuid.UUID] = None
    issuing_authority: Optional[str] = Field(default=None, max_length=255)
    region: Optional[str] = Field(default=None, max_length=128)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    requires_escort: bool = False
    requires_police_escort: bool = False
    max_allowed_weight: Optional[Decimal] = Field(default=None, ge=0)
    max_allowed_height: Optional[Decimal] = Field(default=None, ge=0)
    max_allowed_width: Optional[Decimal] = Field(default=None, ge=0)
    max_allowed_length: Optional[Decimal] = Field(default=None, ge=0)
    conditions: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def tz(cls, v):
        return _require_tz(v)

    @model_validator(mode="after")
    def window(self) -> "PermitCreate":
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be earlier than valid_from.")
        return self


class PermitUpdate(BaseModel):
    issuing_authority: Optional[str] = Field(default=None, max_length=255)
    region: Optional[str] = Field(default=None, max_length=128)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    requires_escort: Optional[bool] = None
    requires_police_escort: Optional[bool] = None
    max_allowed_weight: Optional[Decimal] = Field(default=None, ge=0)
    max_allowed_height: Optional[Decimal] = Field(default=None, ge=0)
    max_allowed_width: Optional[Decimal] = Field(default=None, ge=0)
    max_allowed_length: Optional[Decimal] = Field(default=None, ge=0)
    conditions: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def at_least_one(self) -> "PermitUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class PermitStatusRequest(BaseModel):
    """Optional reason + validity window for permit transitions."""

    reason: Optional[str] = Field(default=None, max_length=512)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class PermitRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    permit_number: str
    shipment_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    vehicle_id: Optional[uuid.UUID] = None
    route_id: Optional[uuid.UUID] = None
    permit_type: PermitType
    status: PermitStatus
    issuing_authority: Optional[str] = None
    region: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    requires_escort: bool
    requires_police_escort: bool
    max_allowed_weight: Optional[Decimal] = None
    max_allowed_height: Optional[Decimal] = None
    max_allowed_width: Optional[Decimal] = None
    max_allowed_length: Optional[Decimal] = None
    conditions: Optional[dict] = None
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[uuid.UUID] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class PermitListParams(BaseModel):
    q: Optional[str] = Field(default=None, max_length=256)
    status: Optional[PermitStatus] = None
    permit_type: Optional[PermitType] = None
    shipment_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _PERMIT_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_PERMIT_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


# --- Escort ----------------------------------------------------------------


class EscortCreate(BaseModel):
    escort_type: EscortType
    shipment_id: Optional[uuid.UUID] = None
    permit_id: Optional[uuid.UUID] = None
    provider_name: Optional[str] = Field(default=None, max_length=255)
    contact_name: Optional[str] = Field(default=None, max_length=255)
    contact_phone: Optional[str] = Field(default=None, max_length=64)
    start_location: Optional[str] = Field(default=None, max_length=512)
    end_location: Optional[str] = Field(default=None, max_length=512)
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)


class EscortScheduleRequest(BaseModel):
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None


class EscortRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    shipment_id: Optional[uuid.UUID] = None
    permit_id: Optional[uuid.UUID] = None
    escort_type: EscortType
    provider_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    start_location: Optional[str] = None
    end_location: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    status: EscortStatus
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class EscortListParams(BaseModel):
    shipment_id: Optional[uuid.UUID] = None
    status: Optional[EscortStatus] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _ESCORT_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_ESCORT_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


# --- Route restriction -----------------------------------------------------


class RouteRestrictionCreate(BaseModel):
    restriction_type: RouteRestrictionType
    region: Optional[str] = Field(default=None, max_length=128)
    road_name: Optional[str] = Field(default=None, max_length=255)
    max_weight: Optional[Decimal] = Field(default=None, ge=0)
    max_height: Optional[Decimal] = Field(default=None, ge=0)
    max_width: Optional[Decimal] = Field(default=None, ge=0)
    max_length: Optional[Decimal] = Field(default=None, ge=0)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    active: bool = True
    notes: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def window(self) -> "RouteRestrictionCreate":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date.")
        return self


class RouteRestrictionUpdate(BaseModel):
    region: Optional[str] = Field(default=None, max_length=128)
    road_name: Optional[str] = Field(default=None, max_length=255)
    max_weight: Optional[Decimal] = Field(default=None, ge=0)
    max_height: Optional[Decimal] = Field(default=None, ge=0)
    max_width: Optional[Decimal] = Field(default=None, ge=0)
    max_length: Optional[Decimal] = Field(default=None, ge=0)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    active: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def at_least_one(self) -> "RouteRestrictionUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


class RouteRestrictionRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    region: Optional[str] = None
    road_name: Optional[str] = None
    restriction_type: RouteRestrictionType
    max_weight: Optional[Decimal] = None
    max_height: Optional[Decimal] = None
    max_width: Optional[Decimal] = None
    max_length: Optional[Decimal] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    active: bool
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


# --- Axle weight -----------------------------------------------------------


class AxleWeightProfileCreate(BaseModel):
    equipment_id: Optional[uuid.UUID] = None
    vehicle_id: Optional[uuid.UUID] = None
    axle_count: Optional[int] = Field(default=None, ge=0)
    total_weight: Optional[Decimal] = Field(default=None, ge=0)
    axle_weights: Optional[List[Any]] = None
    max_axle_weight: Optional[Decimal] = Field(default=None, ge=0)
    is_compliant: bool = True
    notes: Optional[str] = Field(default=None, max_length=4000)


class AxleWeightProfileRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    equipment_id: Optional[uuid.UUID] = None
    vehicle_id: Optional[uuid.UUID] = None
    axle_count: Optional[int] = None
    total_weight: Optional[Decimal] = None
    axle_weights: Optional[List[Any]] = None
    max_axle_weight: Optional[Decimal] = None
    is_compliant: bool
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


# --- Compliance check + dispatch -------------------------------------------


class ComplianceCheckCreate(BaseModel):
    """Request to evaluate compliance for a shipment."""

    shipment_id: uuid.UUID


class ComplianceCheckRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    shipment_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    vehicle_id: Optional[uuid.UUID] = None
    permit_id: Optional[uuid.UUID] = None
    check_type: ComplianceCheckType
    status: ComplianceCheckStatus
    result: Optional[str] = None
    blocking: bool
    failure_reasons: Optional[List[Any]] = None
    evaluated_at: Optional[datetime] = None
    evaluated_by: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)


class ComplianceCheckListParams(BaseModel):
    shipment_id: Optional[uuid.UUID] = None
    status: Optional[ComplianceCheckStatus] = None
    include_deleted: bool = False
    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_ok(cls, v):
        if v not in _CHECK_SORT:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_CHECK_SORT))}.")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class ComplianceOverrideRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=512)


class DispatchGateResult(BaseModel):
    """API projection of the dispatch-gate outcome."""

    allowed: bool
    blocking_reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    required_permits: List[str] = Field(default_factory=list)
    required_escorts: List[str] = Field(default_factory=list)
    compliance_check_ids: List[str] = Field(default_factory=list)


# --- Operator certification ------------------------------------------------


class OperatorCertificationCreate(BaseModel):
    user_id: uuid.UUID
    equipment_category_id: Optional[uuid.UUID] = None
    certification_type: str = Field(min_length=1, max_length=128)
    certification_number: Optional[str] = Field(default=None, max_length=128)
    issuing_authority: Optional[str] = Field(default=None, max_length=255)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def window(self) -> "OperatorCertificationCreate":
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be earlier than valid_from.")
        return self


class OperatorCertificationRead(IdModel, TimestampMixin):
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    equipment_category_id: Optional[uuid.UUID] = None
    certification_type: str
    certification_number: Optional[str] = None
    issuing_authority: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    status: OperatorCertificationStatus
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = None
    version: int
    model_config = ConfigDict(from_attributes=True)
