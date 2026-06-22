"""Pydantic schemas for shipments."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.common import IdModel, TimestampMixin
from app.schemas.enums import ShipmentStatus as ShipmentStatusEnum
from app.schemas.tracking_event import TrackingEventRead


class ShipmentBase(BaseModel):
    """Shared shipment attributes."""

    reference_code: str = Field(min_length=3, max_length=64, description="Human-readable shipment reference.")
    client_id: str = Field(description="Owning client ID.")
    origin_warehouse_id: str = Field(description="Origin warehouse ID.")
    destination_warehouse_id: str = Field(description="Destination warehouse ID.")
    weight_kg: float = Field(gt=0, description="Total shipment weight in kilograms.")
    volume_m3: float = Field(gt=0, description="Total shipment volume in cubic meters.")
    pickup_at: Optional[datetime] = Field(default=None, description="Scheduled pickup datetime (UTC).")
    delivery_due_at: Optional[datetime] = Field(default=None, description="Latest acceptable delivery datetime (UTC).")

    @field_validator("reference_code")
    @classmethod
    def reference_no_whitespace(cls, value: str) -> str:
        if " " in value:
            raise ValueError("Reference code must not contain whitespace.")
        return value

    @field_validator("pickup_at", "delivery_due_at")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Datetime fields must be timezone-aware (UTC).")
        return value


class ShipmentCreate(ShipmentBase):
    """Payload to create a shipment."""
    pass


class ShipmentUpdate(BaseModel):
    """Partial shipment updates; idempotent where applicable."""

    reference_code: Optional[str] = Field(default=None, min_length=3, max_length=64)
    driver_id: Optional[str] = Field(default=None, description="Assign or reassign driver ID.")
    vehicle_id: Optional[str] = Field(default=None, description="Assign or reassign vehicle ID.")
    status: Optional[ShipmentStatusEnum] = Field(default=None, description="Lifecycle status transition.")
    pickup_at: Optional[datetime] = Field(default=None)
    delivery_due_at: Optional[datetime] = Field(default=None)
    delivered_at: Optional[datetime] = Field(default=None)
    cancelled_at: Optional[datetime] = Field(default=None)
    failure_reason: Optional[str] = Field(default=None, max_length=255)

    @field_validator("reference_code")
    @classmethod
    def reference_no_whitespace_update(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and " " in value:
            raise ValueError("Reference code must not contain whitespace.")
        return value

    @field_validator(
        "pickup_at",
        "delivery_due_at",
        "delivered_at",
        "cancelled_at",
    )
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Datetime fields must be timezone-aware (UTC).")
        return value


class ShipmentRead(IdModel, TimestampMixin):
    """Shipment representation returned by the API."""

    reference_code: str
    client_id: str
    origin_warehouse_id: str
    destination_warehouse_id: str
    driver_id: Optional[str]
    vehicle_id: Optional[str]
    status: ShipmentStatusEnum
    weight_kg: float
    volume_m3: float
    pickup_at: Optional[datetime]
    delivery_due_at: Optional[datetime]
    delivered_at: Optional[datetime]
    assigned_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    failure_reason: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class ShipmentWithEvents(ShipmentRead):
    """Shipment with ordered tracking events for richer detail views."""

    tracking_events: List[TrackingEventRead] = Field(
        default_factory=list,
        description="Ordered tracking history.",
    )

    model_config = ConfigDict(from_attributes=True)
