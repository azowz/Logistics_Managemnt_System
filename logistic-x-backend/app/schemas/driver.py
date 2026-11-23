"""Pydantic schemas for driver profiles."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import IdModel, TimestampMixin


class DriverCreate(BaseModel):
    """Payload to create a driver profile for an existing user with role=driver."""

    user_id: uuid.UUID = Field(description="ID of the associated user (must have role=driver).")
    license_number: str = Field(
        min_length=3, max_length=64, description="Government-issued license number."
    )
    license_class: Optional[str] = Field(
        default=None, max_length=32, description="License class/category."
    )
    phone_number: Optional[str] = Field(
        default=None, max_length=32, description="Contact number for dispatch."
    )
    home_warehouse_id: Optional[uuid.UUID] = Field(
        default=None, description="Preferred dispatch warehouse ID."
    )


class DriverUpdate(BaseModel):
    """Mutable driver profile fields."""

    license_number: Optional[str] = Field(default=None, min_length=3, max_length=64)
    license_class: Optional[str] = Field(default=None, max_length=32)
    phone_number: Optional[str] = Field(default=None, max_length=32)
    is_available: Optional[bool] = Field(
        default=None, description="Set driver availability for assignment."
    )
    home_warehouse_id: Optional[uuid.UUID] = Field(default=None)


class DriverRead(IdModel, TimestampMixin):
    """Driver details returned from API."""

    user_id: uuid.UUID
    license_number: str
    license_class: Optional[str]
    phone_number: Optional[str]
    is_available: bool
    home_warehouse_id: Optional[uuid.UUID]

    model_config = ConfigDict(from_attributes=True)
