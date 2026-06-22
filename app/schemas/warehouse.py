"""Pydantic schemas for warehouses."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import IdModel, TimestampMixin


class WarehouseBase(BaseModel):
    """Shared address and capacity attributes."""

    code: str = Field(min_length=2, max_length=32, description="Unique warehouse code.")
    name: str = Field(min_length=2, max_length=255)
    address_line1: str = Field(max_length=255)
    address_line2: Optional[str] = Field(default=None, max_length=255)
    city: str = Field(max_length=128)
    state: Optional[str] = Field(default=None, max_length=128)
    country: str = Field(max_length=128)
    postal_code: Optional[str] = Field(default=None, max_length=32)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    capacity_weight_kg: float = Field(gt=0, description="Total weight capacity.")
    capacity_volume_m3: float = Field(gt=0, description="Total volume capacity.")
    max_daily_shipments: Optional[int] = Field(default=None, ge=1, description="Optional throughput guardrail.")

    @field_validator("code")
    @classmethod
    def code_no_whitespace(cls, value: str) -> str:
        """Prevent whitespace in warehouse codes to keep them URL-safe."""
        if " " in value:
            raise ValueError("Warehouse code must not contain whitespace.")
        return value


class WarehouseCreate(WarehouseBase):
    """Payload to create a warehouse."""
    pass


class WarehouseUpdate(BaseModel):
    """Partial updates for warehouse metadata."""

    name: Optional[str] = Field(default=None, max_length=255)
    address_line1: Optional[str] = Field(default=None, max_length=255)
    address_line2: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=128)
    state: Optional[str] = Field(default=None, max_length=128)
    country: Optional[str] = Field(default=None, max_length=128)
    postal_code: Optional[str] = Field(default=None, max_length=32)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    capacity_weight_kg: Optional[float] = Field(default=None, gt=0)
    capacity_volume_m3: Optional[float] = Field(default=None, gt=0)
    max_daily_shipments: Optional[int] = Field(default=None, ge=1)


class WarehouseRead(IdModel, TimestampMixin, WarehouseBase):
    """Warehouse representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)
