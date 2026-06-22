"""Schemas for driver-facing self-service endpoints (mobile app contract).

These back the routes the Mesaar driver app expects (see docs/api-gap-analysis.md)
and mirror the mobile types in mobile/src/api/types.ts.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.driver import DriverRead


class PhoneLoginRequest(BaseModel):
    """Driver phone login. OTP verification is stubbed for now (see service)."""

    phone: str = Field(description="E.164 phone, e.g. +966512345678.")
    otp: Optional[str] = Field(default=None, description="One-time code (future).")


class DriverSessionResponse(BaseModel):
    """Token + driver profile returned to the mobile app on login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds.")
    driver: DriverRead


class AvailabilityUpdate(BaseModel):
    """Toggle the calling driver's online/offline availability."""

    is_available: bool


class DriverStatsRead(BaseModel):
    """Today's KPIs for the authenticated driver."""

    earnings_sar: float = Field(default=0)
    trips: int = Field(default=0)
    online_hours: float = Field(default=0)
    distance_km: float = Field(default=0)
    date: date


class ShipmentOfferRead(BaseModel):
    """Enriched ready-shipment offer surfaced to drivers."""

    id: str
    reference_code: str
    origin_city: Optional[str] = None
    destination_city: Optional[str] = None
    cargo_type: Optional[str] = None
    weight_kg: float
    price_sar: Optional[float] = None
    required_vehicle_label: Optional[str] = None
    distance_km: Optional[float] = None
