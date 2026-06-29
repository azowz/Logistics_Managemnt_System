"""Customer domain Pydantic schemas.

Split into request (write) and response (read) models following the pattern
established by ``app.schemas.user`` and ``app.schemas.shipment``.

Schemas never import SQLAlchemy models — only domain enums.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.models.enums import CreditStatus, CustomerStatus, CustomerType, RiskLevel
from app.schemas.common import IdModel, TimestampMixin

# Allowed sort fields (whitelist to prevent injection via ORDER BY).
_SORTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "code",
        "company_name",
        "commercial_name",
        "status",
        "customer_type",
        "risk_level",
        "credit_status",
        "country",
        "city",
        "created_at",
        "updated_at",
    }
)


# ---------------------------------------------------------------------------
# Write schemas (request bodies)
# ---------------------------------------------------------------------------


class CustomerCreate(BaseModel):
    """Payload for creating a new customer."""

    # Identity
    code: str = Field(
        min_length=1,
        max_length=64,
        description="Internal customer code, unique within the tenant.",
    )
    customer_type: CustomerType = Field(
        default=CustomerType.CORPORATE,
        description="Classification of the customer entity.",
    )
    industry: Optional[str] = Field(
        default=None, max_length=128, description="Business sector / industry."
    )

    # Names
    company_name: str = Field(
        min_length=1,
        max_length=255,
        description="Registered company or individual name.",
    )
    commercial_name: Optional[str] = Field(
        default=None, max_length=255, description="Trade / DBA name."
    )

    # Legal / Tax
    tax_number: Optional[str] = Field(
        default=None, max_length=64, description="Tax identification number."
    )
    commercial_registration: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Commercial registration number (unique per tenant when provided).",
    )
    vat_number: Optional[str] = Field(
        default=None,
        max_length=64,
        description="VAT registration number (unique per tenant when provided).",
    )

    # Contact
    contact_person: Optional[str] = Field(
        default=None, max_length=255, description="Primary contact person name."
    )
    primary_phone: Optional[str] = Field(
        default=None, max_length=32, description="Primary phone number."
    )
    secondary_phone: Optional[str] = Field(
        default=None, max_length=32, description="Secondary / alternative phone."
    )
    primary_email: Optional[EmailStr] = Field(
        default=None, description="Primary contact email address."
    )
    secondary_email: Optional[EmailStr] = Field(
        default=None, description="Secondary contact email address."
    )

    # Address
    country: Optional[str] = Field(
        default=None, max_length=128, description="Country name or ISO code."
    )
    city: Optional[str] = Field(default=None, max_length=128, description="City.")
    district: Optional[str] = Field(
        default=None, max_length=128, description="District or neighbourhood."
    )
    address: Optional[str] = Field(
        default=None, description="Free-form postal address."
    )
    latitude: Optional[Decimal] = Field(
        default=None, ge=-90, le=90, description="GPS latitude (±90°)."
    )
    longitude: Optional[Decimal] = Field(
        default=None, ge=-180, le=180, description="GPS longitude (±180°)."
    )

    # Preferences
    preferred_language: Optional[str] = Field(
        default=None,
        max_length=8,
        description="BCP-47 language tag, e.g. 'ar' or 'en'.",
    )

    # Operational
    status: CustomerStatus = Field(
        default=CustomerStatus.ACTIVE,
        description="Initial operational status.",
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.LOW, description="Credit / operational risk classification."
    )
    credit_status: CreditStatus = Field(
        default=CreditStatus.GOOD, description="Current credit standing."
    )

    # Free-form
    notes: Optional[str] = Field(
        default=None, description="Internal notes visible only to tenant staff."
    )
    tags: Optional[List[str]] = Field(
        default=None, description="Free-form string labels for search/grouping."
    )

    @field_validator("code")
    @classmethod
    def code_no_whitespace(cls, value: str) -> str:
        if re.search(r"\s", value):
            raise ValueError("Customer code must not contain whitespace.")
        return value.upper()

    @field_validator("preferred_language")
    @classmethod
    def language_tag_format(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not re.fullmatch(r"[a-zA-Z]{2,8}(-[a-zA-Z0-9]{1,8})*", value):
            raise ValueError("preferred_language must be a valid BCP-47 tag (e.g. 'ar', 'en-US').")
        return value


class CustomerUpdate(BaseModel):
    """Mutable fields for updating an existing customer (all optional)."""

    customer_type: Optional[CustomerType] = None
    industry: Optional[str] = Field(default=None, max_length=128)

    company_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    commercial_name: Optional[str] = Field(default=None, max_length=255)

    tax_number: Optional[str] = Field(default=None, max_length=64)
    commercial_registration: Optional[str] = Field(default=None, max_length=64)
    vat_number: Optional[str] = Field(default=None, max_length=64)

    contact_person: Optional[str] = Field(default=None, max_length=255)
    primary_phone: Optional[str] = Field(default=None, max_length=32)
    secondary_phone: Optional[str] = Field(default=None, max_length=32)
    primary_email: Optional[EmailStr] = None
    secondary_email: Optional[EmailStr] = None

    country: Optional[str] = Field(default=None, max_length=128)
    city: Optional[str] = Field(default=None, max_length=128)
    district: Optional[str] = Field(default=None, max_length=128)
    address: Optional[str] = None
    latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180)

    preferred_language: Optional[str] = Field(default=None, max_length=8)
    risk_level: Optional[RiskLevel] = None
    credit_status: Optional[CreditStatus] = None

    notes: Optional[str] = None
    tags: Optional[List[str]] = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "CustomerUpdate":
        provided = {k: v for k, v in self.model_dump(exclude_unset=True).items() if v is not None}
        if not provided:
            raise ValueError("At least one field must be provided for update.")
        return self


class CustomerStatusUpdate(BaseModel):
    """Dedicated payload for status transitions (activate / suspend)."""

    reason: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Human-readable reason for the status change.",
    )


# ---------------------------------------------------------------------------
# Read schema (response body)
# ---------------------------------------------------------------------------


class CustomerRead(IdModel, TimestampMixin):
    """Complete customer representation returned by the API."""

    tenant_id: uuid.UUID = Field(description="Owning tenant identifier.")

    code: str
    customer_type: CustomerType
    industry: Optional[str] = None

    company_name: str
    commercial_name: Optional[str] = None

    tax_number: Optional[str] = None
    commercial_registration: Optional[str] = None
    vat_number: Optional[str] = None

    contact_person: Optional[str] = None
    primary_phone: Optional[str] = None
    secondary_phone: Optional[str] = None
    primary_email: Optional[str] = None
    secondary_email: Optional[str] = None

    country: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None

    preferred_language: Optional[str] = None
    status: CustomerStatus
    risk_level: RiskLevel
    credit_status: CreditStatus

    notes: Optional[str] = None
    tags: Optional[List[str]] = None

    deleted_at: Optional[datetime] = None
    deleted_by: Optional[uuid.UUID] = None

    version: int

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# List / search query parameters
# ---------------------------------------------------------------------------


class CustomerListParams(BaseModel):
    """Query parameters accepted by ``GET /customers`` and ``GET /customers/search``."""

    # Free-text search (applied to code, company_name, commercial_name, primary_email)
    q: Optional[str] = Field(default=None, max_length=256, description="Full-text search query.")

    # Filters
    status: Optional[CustomerStatus] = None
    customer_type: Optional[CustomerType] = None
    risk_level: Optional[RiskLevel] = None
    credit_status: Optional[CreditStatus] = None
    country: Optional[str] = Field(default=None, max_length=128)
    city: Optional[str] = Field(default=None, max_length=128)
    include_deleted: bool = Field(
        default=False, description="When true, include soft-deleted customers."
    )

    # Sorting
    sort_by: str = Field(
        default="created_at",
        description=f"Field to sort by. One of: {', '.join(sorted(_SORTABLE_FIELDS))}.",
    )
    sort_dir: str = Field(
        default="desc",
        pattern="^(asc|desc)$",
        description="Sort direction: 'asc' or 'desc'.",
    )

    # Pagination
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
