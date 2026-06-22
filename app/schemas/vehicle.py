"""Pydantic schemas for vehicle assets."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import VehicleStatus
from app.schemas.common import IdModel, TimestampMixin


class VehicleBase(BaseModel):
    """Shared vehicle attributes."""

    plate_number: str = Field(min_length=2, max_length=32, description="Unique license plate.")
    vin: Optional[str] = Field(default=None, max_length=64, description="Vehicle identification number.")
    capacity_weight_kg: float = Field(gt=0, description="Maximum payload weight.")
    capacity_volume_m3: float = Field(gt=0, description="Maximum payload volume.")
    home_warehouse_id: Optional[str] = Field(default=None, description="Home warehouse reference.")

    @field_validator("plate_number")
    @classmethod
    def plate_no_whitespace(cls, value: str) -> str:
        """Prevent whitespace in plate numbers to avoid parsing errors."""
        if " " in value:
            raise ValueError("Plate number must not contain whitespace.")
        return value


class VehicleCreate(VehicleBase):
    """Payload to create a vehicle."""

    status: VehicleStatus = Field(default=VehicleStatus.ACTIVE, description="Operational status.")


class VehicleUpdate(BaseModel):
    """Mutable fields for vehicle updates."""

    plate_number: Optional[str] = Field(default=None, min_length=2, max_length=32)
    vin: Optional[str] = Field(default=None, max_length=64)
    status: Optional[VehicleStatus] = Field(default=None)
    capacity_weight_kg: Optional[float] = Field(default=None, gt=0)
    capacity_volume_m3: Optional[float] = Field(default=None, gt=0)
    home_warehouse_id: Optional[str] = Field(default=None)

    @field_validator("plate_number")
    @classmethod
    def plate_no_whitespace_update(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and " " in value:
            raise ValueError("Plate number must not contain whitespace.")
        return value


class VehicleRead(IdModel, TimestampMixin, VehicleBase):
    """Vehicle representation returned by the API."""

    status: VehicleStatus

    model_config = ConfigDict(from_attributes=True)
