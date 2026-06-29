"""Pydantic schemas for the Equipment & Asset domain (Sprint 6).

Request (write) and response (read) models mirroring ``app.schemas.order`` /
``app.schemas.shipment``. Schemas import only domain enums, never ORM models.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    EquipmentAvailability,
    EquipmentOwnershipType,
    EquipmentStatus,
)
from app.schemas.common import IdModel, TimestampMixin

_SORTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "equipment_code",
        "asset_tag",
        "name",
        "status",
        "availability_status",
        "ownership_type",
        "year",
        "weight_kg",
        "created_at",
        "updated_at",
    }
)

_MIN_YEAR = 1900
_MAX_YEAR = 2100


def _validate_year(value: Optional[int]) -> Optional[int]:
    if value is not None and not (_MIN_YEAR <= value <= _MAX_YEAR):
        raise ValueError(f"year must be between {_MIN_YEAR} and {_MAX_YEAR}.")
    return value


def _no_whitespace(value: Optional[str], field: str) -> Optional[str]:
    if value is not None and re.search(r"\s", value):
        raise ValueError(f"{field} must not contain whitespace.")
    return value


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class EquipmentCreate(BaseModel):
    """Payload for creating an equipment unit (starts active/available)."""

    # ``model_id`` / ``model_name`` are domain fields, not Pydantic config.
    model_config = ConfigDict(protected_namespaces=())

    equipment_code: Optional[str] = Field(
        default=None, min_length=2, max_length=64,
        description="Tenant-unique code; auto-generated when omitted.",
    )
    asset_tag: str = Field(min_length=1, max_length=64)
    category_id: uuid.UUID
    model_id: Optional[uuid.UUID] = None

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    serial_number: Optional[str] = Field(default=None, max_length=128)
    manufacturer: Optional[str] = Field(default=None, max_length=128)
    model_name: Optional[str] = Field(default=None, max_length=128)
    year: Optional[int] = None
    ownership_type: EquipmentOwnershipType = Field(default=EquipmentOwnershipType.OWNED)

    weight_kg: Optional[Decimal] = Field(default=None, ge=0)
    length_m: Optional[Decimal] = Field(default=None, ge=0)
    width_m: Optional[Decimal] = Field(default=None, ge=0)
    height_m: Optional[Decimal] = Field(default=None, ge=0)
    volume_m3: Optional[Decimal] = Field(default=None, ge=0)

    requires_permit: bool = False
    requires_escort: bool = False
    requires_special_handling: bool = False
    hazardous: bool = False
    temperature_sensitive: bool = False
    insurance_required: bool = False

    current_warehouse_id: Optional[uuid.UUID] = None
    current_location: Optional[str] = Field(default=None, max_length=512)
    notes: Optional[str] = Field(default=None, max_length=4000)
    tags: Optional[List[str]] = None

    @field_validator("equipment_code")
    @classmethod
    def code_no_whitespace(cls, v: Optional[str]) -> Optional[str]:
        return _no_whitespace(v, "equipment_code")

    @field_validator("year")
    @classmethod
    def year_in_range(cls, v: Optional[int]) -> Optional[int]:
        return _validate_year(v)

    @field_validator("tags")
    @classmethod
    def tags_valid(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            if any((not isinstance(t, str)) or not t.strip() for t in v):
                raise ValueError("tags must be a list of non-empty strings.")
        return v


class EquipmentUpdate(BaseModel):
    """Mutable equipment fields (all optional). Status is not editable here."""

    model_config = ConfigDict(protected_namespaces=())

    equipment_code: Optional[str] = Field(default=None, min_length=2, max_length=64)
    asset_tag: Optional[str] = Field(default=None, min_length=1, max_length=64)
    category_id: Optional[uuid.UUID] = None
    model_id: Optional[uuid.UUID] = None

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    serial_number: Optional[str] = Field(default=None, max_length=128)
    manufacturer: Optional[str] = Field(default=None, max_length=128)
    model_name: Optional[str] = Field(default=None, max_length=128)
    year: Optional[int] = None
    ownership_type: Optional[EquipmentOwnershipType] = None

    weight_kg: Optional[Decimal] = Field(default=None, ge=0)
    length_m: Optional[Decimal] = Field(default=None, ge=0)
    width_m: Optional[Decimal] = Field(default=None, ge=0)
    height_m: Optional[Decimal] = Field(default=None, ge=0)
    volume_m3: Optional[Decimal] = Field(default=None, ge=0)

    requires_permit: Optional[bool] = None
    requires_escort: Optional[bool] = None
    requires_special_handling: Optional[bool] = None
    hazardous: Optional[bool] = None
    temperature_sensitive: Optional[bool] = None
    insurance_required: Optional[bool] = None

    current_warehouse_id: Optional[uuid.UUID] = None
    current_location: Optional[str] = Field(default=None, max_length=512)
    notes: Optional[str] = Field(default=None, max_length=4000)
    tags: Optional[List[str]] = None

    @field_validator("year")
    @classmethod
    def year_in_range(cls, v: Optional[int]) -> Optional[int]:
        return _validate_year(v)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "EquipmentUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


# --- action requests ---


class EquipmentReserveRequest(BaseModel):
    """Payload for reserving equipment (optional reference to the holding job)."""

    reference: Optional[str] = Field(default=None, max_length=128)


class EquipmentMaintenanceRequest(BaseModel):
    """Payload for starting/decommissioning with an optional reason."""

    reason: Optional[str] = Field(default=None, max_length=512)


class EquipmentAssignmentRequest(BaseModel):
    """Payload for binding equipment to a shipment."""

    shipment_id: uuid.UUID


class EquipmentStatusUpdate(BaseModel):
    """Generic optional-reason payload for status transitions."""

    reason: Optional[str] = Field(default=None, max_length=512)


# ---------------------------------------------------------------------------
# Read schema
# ---------------------------------------------------------------------------


class EquipmentRead(IdModel, TimestampMixin):
    """Complete equipment representation returned by the API."""

    tenant_id: uuid.UUID
    equipment_code: str
    asset_tag: str
    category_id: uuid.UUID
    model_id: Optional[uuid.UUID] = None

    name: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    model_name: Optional[str] = None
    year: Optional[int] = None
    ownership_type: EquipmentOwnershipType

    status: EquipmentStatus
    availability_status: EquipmentAvailability

    weight_kg: Optional[Decimal] = None
    length_m: Optional[Decimal] = None
    width_m: Optional[Decimal] = None
    height_m: Optional[Decimal] = None
    volume_m3: Optional[Decimal] = None

    requires_permit: bool
    requires_escort: bool
    requires_special_handling: bool
    hazardous: bool
    temperature_sensitive: bool
    insurance_required: bool

    current_warehouse_id: Optional[uuid.UUID] = None
    current_location: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None

    deleted_at: Optional[datetime] = None
    deleted_by: Optional[uuid.UUID] = None
    version: int

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


# ---------------------------------------------------------------------------
# List / search params
# ---------------------------------------------------------------------------


class EquipmentListParams(BaseModel):
    """Query parameters for ``GET /equipment`` and ``GET /equipment/search``."""

    model_config = ConfigDict(protected_namespaces=())

    q: Optional[str] = Field(default=None, max_length=256)

    status: Optional[EquipmentStatus] = None
    availability_status: Optional[EquipmentAvailability] = None
    category_id: Optional[uuid.UUID] = None
    model_id: Optional[uuid.UUID] = None
    current_warehouse_id: Optional[uuid.UUID] = None
    include_deleted: bool = False

    sort_by: str = Field(default="created_at")
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")

    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_field_allowed(cls, value: str) -> str:
        if value not in _SORTABLE_FIELDS:
            raise ValueError(
                f"sort_by must be one of: {', '.join(sorted(_SORTABLE_FIELDS))}."
            )
        return value

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
