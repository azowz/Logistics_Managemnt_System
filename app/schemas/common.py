"""Shared Pydantic schema utilities and base classes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TimestampMixin(BaseModel):
    """Read-only timestamps returned by the API."""

    created_at: datetime = Field(description="UTC timestamp when the resource was created.")
    updated_at: datetime = Field(description="UTC timestamp when the resource was last updated.")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        """Guarantee timestamps are timezone-aware and normalized to UTC."""
        if value.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware.")
        return value.astimezone(timezone.utc)


class IdModel(BaseModel):
    """Base model exposing an immutable identifier."""

    id: str = Field(description="Resource identifier (UUID).")

    model_config = ConfigDict(from_attributes=True)
