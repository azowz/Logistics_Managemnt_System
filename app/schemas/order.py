"""Order domain Pydantic schemas.

Split into request (write) and response (read) models, mirroring
``app.schemas.customer``. Schemas never import SQLAlchemy models — only domain
enums.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models.enums import OrderPriority, OrderSource, OrderStatus, OrderType
from app.schemas.common import IdModel, TimestampMixin

# Whitelist of sortable fields (prevents ORDER BY injection).
_SORTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "order_number",
        "status",
        "order_type",
        "order_source",
        "priority",
        "customer_id",
        "requested_pickup_date",
        "requested_delivery_date",
        "created_at",
        "updated_at",
    }
)


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class OrderCreate(BaseModel):
    """Payload for creating a new order. The order always starts in ``draft``."""

    customer_id: uuid.UUID = Field(description="Owning customer (must exist in tenant).")
    order_number: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Tenant-unique order number; auto-generated when omitted.",
    )

    order_type: OrderType = Field(default=OrderType.STANDARD)
    order_source: OrderSource = Field(default=OrderSource.WEB)
    priority: OrderPriority = Field(default=OrderPriority.NORMAL)

    requested_pickup_date: Optional[datetime] = None
    requested_delivery_date: Optional[datetime] = None

    pickup_location: Optional[str] = Field(default=None, max_length=2000)
    delivery_location: Optional[str] = Field(default=None, max_length=2000)
    pickup_latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    pickup_longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180)
    delivery_latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    delivery_longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180)

    distance_km: Optional[Decimal] = Field(default=None, ge=0)
    estimated_duration_minutes: Optional[int] = Field(default=None, ge=0)

    cargo_description: Optional[str] = Field(default=None, max_length=4000)
    cargo_weight_kg: Optional[Decimal] = Field(default=None, ge=0)
    cargo_volume_m3: Optional[Decimal] = Field(default=None, ge=0)
    dangerous_goods: bool = Field(default=False)
    temperature_requirements: Optional[str] = Field(default=None, max_length=128)
    is_fragile: bool = Field(default=False)
    insurance_required: bool = Field(default=False)

    special_instructions: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if re.search(r"\s", value):
            raise ValueError("Order number must not contain whitespace.")
        return value.upper()

    @model_validator(mode="after")
    def delivery_after_pickup(self) -> "OrderCreate":
        if (
            self.requested_pickup_date is not None
            and self.requested_delivery_date is not None
            and self.requested_delivery_date < self.requested_pickup_date
        ):
            raise ValueError(
                "requested_delivery_date must not be earlier than requested_pickup_date."
            )
        return self


class OrderUpdate(BaseModel):
    """Mutable fields for an existing order (all optional). Status is immutable here."""

    order_type: Optional[OrderType] = None
    order_source: Optional[OrderSource] = None
    priority: Optional[OrderPriority] = None

    requested_pickup_date: Optional[datetime] = None
    requested_delivery_date: Optional[datetime] = None

    pickup_location: Optional[str] = Field(default=None, max_length=2000)
    delivery_location: Optional[str] = Field(default=None, max_length=2000)
    pickup_latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    pickup_longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180)
    delivery_latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    delivery_longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180)

    distance_km: Optional[Decimal] = Field(default=None, ge=0)
    estimated_duration_minutes: Optional[int] = Field(default=None, ge=0)

    cargo_description: Optional[str] = Field(default=None, max_length=4000)
    cargo_weight_kg: Optional[Decimal] = Field(default=None, ge=0)
    cargo_volume_m3: Optional[Decimal] = Field(default=None, ge=0)
    dangerous_goods: Optional[bool] = None
    temperature_requirements: Optional[str] = Field(default=None, max_length=128)
    is_fragile: Optional[bool] = None
    insurance_required: Optional[bool] = None

    special_instructions: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "OrderUpdate":
        provided = self.model_dump(exclude_unset=True)
        if not provided:
            raise ValueError("At least one field must be provided for update.")
        return self


class OrderStatusUpdate(BaseModel):
    """Payload for status transitions that only carry an optional reason."""

    reason: Optional[str] = Field(default=None, max_length=512)


class OrderAssignRequest(BaseModel):
    """Payload for assigning an order to a dispatcher."""

    assigned_dispatcher_id: uuid.UUID = Field(
        description="User id of the dispatcher taking ownership."
    )
    reason: Optional[str] = Field(default=None, max_length=512)


# ---------------------------------------------------------------------------
# Read schema
# ---------------------------------------------------------------------------


class OrderRead(IdModel, TimestampMixin):
    """Complete order representation returned by the API."""

    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    order_number: str

    order_type: OrderType
    order_source: OrderSource
    priority: OrderPriority
    status: OrderStatus

    requested_pickup_date: Optional[datetime] = None
    requested_delivery_date: Optional[datetime] = None

    pickup_location: Optional[str] = None
    delivery_location: Optional[str] = None
    pickup_latitude: Optional[Decimal] = None
    pickup_longitude: Optional[Decimal] = None
    delivery_latitude: Optional[Decimal] = None
    delivery_longitude: Optional[Decimal] = None

    distance_km: Optional[Decimal] = None
    estimated_duration_minutes: Optional[int] = None

    cargo_description: Optional[str] = None
    cargo_weight_kg: Optional[Decimal] = None
    cargo_volume_m3: Optional[Decimal] = None
    dangerous_goods: bool
    temperature_requirements: Optional[str] = None
    is_fragile: bool
    insurance_required: bool

    special_instructions: Optional[str] = None
    assigned_dispatcher_id: Optional[uuid.UUID] = None

    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    failure_reason: Optional[str] = None

    deleted_at: Optional[datetime] = None
    deleted_by: Optional[uuid.UUID] = None

    version: int

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# List / search params
# ---------------------------------------------------------------------------


class OrderListParams(BaseModel):
    """Query parameters for ``GET /orders`` and ``GET /orders/search``."""

    q: Optional[str] = Field(default=None, max_length=256)

    status: Optional[OrderStatus] = None
    order_type: Optional[OrderType] = None
    order_source: Optional[OrderSource] = None
    priority: Optional[OrderPriority] = None
    customer_id: Optional[uuid.UUID] = None
    assigned_dispatcher_id: Optional[uuid.UUID] = None
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
