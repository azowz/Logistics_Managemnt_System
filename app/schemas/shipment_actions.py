"""Action-specific schemas for shipment operations."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.enums import ShipmentStatus


class AssignmentRequest(BaseModel):
    """Request payload to assign a driver and vehicle to a shipment."""

    driver_id: str = Field(description="Driver ID to assign.")
    vehicle_id: str = Field(description="Vehicle ID to assign.")


class StatusUpdateRequest(BaseModel):
    """Request payload to transition a shipment's status."""

    status: ShipmentStatus = Field(description="Target shipment status.")
