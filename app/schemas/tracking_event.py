"""Pydantic schemas for shipment tracking events."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import IdModel, TimestampMixin
from app.schemas.enums import ShipmentStatus, TrackingEventType


class TrackingEventCreate(BaseModel):
    """Payload to append a tracking event to a shipment."""

    shipment_id: str = Field(description="ID of the shipment this event belongs to.")
    event_type: TrackingEventType = Field(description="Type of tracking event.")
    status: Optional[ShipmentStatus] = Field(
        default=None,
        description="Shipment status after this event, if applicable.",
    )
    event_time: datetime = Field(description="Time the event occurred (UTC).")
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    notes: Optional[str] = Field(default=None, description="Free-form notes about the event.")
    recorded_by_user_id: Optional[str] = Field(
        default=None,
        description="User who recorded the event (driver or manager).",
    )
    evidence_url: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Link to supporting evidence (e.g., POD image).",
    )

    @field_validator("event_time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("event_time must be timezone-aware (UTC).")
        return value


class TrackingEventRead(IdModel, TimestampMixin):
    """Tracking event representation returned by the API."""

    shipment_id: str
    event_type: TrackingEventType
    status: Optional[ShipmentStatus]
    event_time: datetime
    latitude: Optional[float]
    longitude: Optional[float]
    notes: Optional[str]
    recorded_by_user_id: Optional[str]
    evidence_url: Optional[str]

    model_config = ConfigDict(from_attributes=True)
