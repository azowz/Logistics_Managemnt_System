"""Pydantic schemas for the Shipment domain (Sprint 5).

Split into request (write) and response (read) models, mirroring
``app.schemas.order``. Schemas never import SQLAlchemy models — only domain
enums. UUID id-bearing fields are typed as :class:`uuid.UUID`; the primary
``id`` is exposed as a string via :class:`~app.schemas.common.IdModel`.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import ShipmentPriority, ShipmentStatus
from app.schemas.common import IdModel, TimestampMixin
from app.schemas.tracking_event import TrackingEventRead

# Whitelist of sortable fields (prevents ORDER BY injection).
_SORTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "reference_code",
        "status",
        "priority",
        "weight_kg",
        "volume_m3",
        "delivery_due_at",
        "pickup_at",
        "created_at",
        "updated_at",
    }
)


def _validate_currency(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.upper()
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency_code must be a 3-letter ISO-4217 code.")
    return value


def _require_tz(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        raise ValueError("Datetime fields must be timezone-aware (UTC).")
    return value


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class ShipmentCreate(BaseModel):
    """Payload for creating a shipment. The shipment always starts in ``created``."""

    reference_code: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=64,
        description="Tenant-unique reference; auto-generated when omitted.",
    )
    client_id: uuid.UUID = Field(description="Owning client (user) id.")
    order_id: Optional[uuid.UUID] = Field(
        default=None, description="Upstream order this shipment fulfils."
    )
    origin_warehouse_id: uuid.UUID = Field(description="Origin warehouse id.")
    destination_warehouse_id: uuid.UUID = Field(description="Destination warehouse id.")
    equipment_id: Optional[uuid.UUID] = Field(
        default=None, description="Optional equipment reference."
    )

    priority: ShipmentPriority = Field(default=ShipmentPriority.NORMAL)

    weight_kg: Decimal = Field(gt=0, description="Total weight in kilograms.")
    volume_m3: Decimal = Field(gt=0, description="Total volume in cubic meters.")

    cargo_type: Optional[str] = Field(default=None, max_length=128)
    cargo_description: Optional[str] = Field(default=None, max_length=4000)
    price_sar: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    required_vehicle_type: Optional[str] = Field(default=None, max_length=64)

    pickup_at: Optional[datetime] = None
    delivery_due_at: Optional[datetime] = None

    @field_validator("reference_code")
    @classmethod
    def reference_no_whitespace(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and re.search(r"\s", value):
            raise ValueError("Reference code must not contain whitespace.")
        return value

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return _validate_currency(value)

    @field_validator("pickup_at", "delivery_due_at")
    @classmethod
    def require_tz(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _require_tz(value)

    @model_validator(mode="after")
    def pickup_before_delivery(self) -> "ShipmentCreate":
        if (
            self.pickup_at is not None
            and self.delivery_due_at is not None
            and self.delivery_due_at < self.pickup_at
        ):
            raise ValueError("delivery_due_at must not be earlier than pickup_at.")
        return self


class ShipmentUpdate(BaseModel):
    """Mutable shipment fields (all optional). Status/assignment are not editable here."""

    reference_code: Optional[str] = Field(default=None, min_length=3, max_length=64)
    order_id: Optional[uuid.UUID] = None
    origin_warehouse_id: Optional[uuid.UUID] = None
    destination_warehouse_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None
    priority: Optional[ShipmentPriority] = None

    weight_kg: Optional[Decimal] = Field(default=None, gt=0)
    volume_m3: Optional[Decimal] = Field(default=None, gt=0)

    cargo_type: Optional[str] = Field(default=None, max_length=128)
    cargo_description: Optional[str] = Field(default=None, max_length=4000)
    price_sar: Optional[Decimal] = Field(default=None, ge=0)
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    required_vehicle_type: Optional[str] = Field(default=None, max_length=64)

    pickup_at: Optional[datetime] = None
    delivery_due_at: Optional[datetime] = None

    @field_validator("reference_code")
    @classmethod
    def reference_no_whitespace(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and re.search(r"\s", value):
            raise ValueError("Reference code must not contain whitespace.")
        return value

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        return _validate_currency(value)

    @field_validator("pickup_at", "delivery_due_at")
    @classmethod
    def require_tz(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _require_tz(value)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "ShipmentUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update.")
        return self


# ---------------------------------------------------------------------------
# Action request schemas
# ---------------------------------------------------------------------------


class ShipmentAssignRequest(BaseModel):
    """Payload for assigning a driver and vehicle to a shipment."""

    driver_id: uuid.UUID = Field(description="Driver to assign.")
    vehicle_id: uuid.UUID = Field(description="Vehicle to assign.")
    reason: Optional[str] = Field(default=None, max_length=512)


class ShipmentReasonRequest(BaseModel):
    """Generic payload carrying an optional human-readable reason."""

    reason: Optional[str] = Field(default=None, max_length=512)


# Distinct, explicitly-named aliases for the lifecycle endpoints (OpenAPI clarity).
class ShipmentDelayRequest(ShipmentReasonRequest):
    """Reason payload for marking a shipment delayed."""


class ShipmentCancelRequest(ShipmentReasonRequest):
    """Reason payload for cancelling a shipment."""


class ShipmentFailRequest(ShipmentReasonRequest):
    """Reason payload for failing a shipment."""


class ShipmentReturnRequest(ShipmentReasonRequest):
    """Reason payload for returning a shipment."""


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class ShipmentRead(IdModel, TimestampMixin):
    """Complete shipment representation returned by the API."""

    tenant_id: uuid.UUID
    reference_code: str
    client_id: uuid.UUID
    order_id: Optional[uuid.UUID] = None
    origin_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
    driver_id: Optional[uuid.UUID] = None
    vehicle_id: Optional[uuid.UUID] = None
    equipment_id: Optional[uuid.UUID] = None

    status: ShipmentStatus
    priority: ShipmentPriority

    weight_kg: Decimal
    volume_m3: Decimal
    cargo_type: Optional[str] = None
    cargo_description: Optional[str] = None
    price_sar: Optional[Decimal] = None
    currency_code: str
    required_vehicle_type: Optional[str] = None

    pickup_at: Optional[datetime] = None
    delivery_due_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    return_reason: Optional[str] = None

    deleted_at: Optional[datetime] = None
    deleted_by: Optional[uuid.UUID] = None

    version: int

    model_config = ConfigDict(from_attributes=True)


class ShipmentWithEvents(ShipmentRead):
    """Shipment with ordered tracking events for richer detail views."""

    tracking_events: List[TrackingEventRead] = Field(
        default_factory=list, description="Ordered tracking history."
    )

    model_config = ConfigDict(from_attributes=True)


class ShipmentStatusResponse(BaseModel):
    """Lightweight status projection (id + status + priority)."""

    id: uuid.UUID
    status: ShipmentStatus
    priority: ShipmentPriority

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# List / search params
# ---------------------------------------------------------------------------


class ShipmentListParams(BaseModel):
    """Query parameters for ``GET /shipments`` and ``GET /shipments/search``."""

    q: Optional[str] = Field(default=None, max_length=256)

    status: Optional[ShipmentStatus] = None
    priority: Optional[ShipmentPriority] = None
    driver_id: Optional[uuid.UUID] = None
    vehicle_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None
    client_id: Optional[uuid.UUID] = None
    origin_warehouse_id: Optional[uuid.UUID] = None
    destination_warehouse_id: Optional[uuid.UUID] = None
    include_deleted: bool = False

    sort_by: str = Field(default="created_at")
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")

    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)

    @field_validator("sort_by")
    @classmethod
    def sort_field_allowed(cls, value: str) -> str:
        if value not in _SORTABLE_FIELDS:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(_SORTABLE_FIELDS))}.")
        return value

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
