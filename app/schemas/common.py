"""Shared Pydantic schema utilities and base classes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_currency_code(value: Optional[str]) -> Optional[str]:
    """Upper-case and validate an ISO-4217 code (``None`` passes through)."""
    if value is None:
        return None
    value = value.upper()
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency_code must be a 3-letter ISO-4217 code.")
    return value


def require_aware_datetime(value: Optional[datetime]) -> Optional[datetime]:
    """Reject naive datetimes on write payloads; every timestamp is stored as UTC."""
    if value is not None and value.tzinfo is None:
        raise ValueError("Datetime fields must be timezone-aware (UTC).")
    return value


class TimestampMixin(BaseModel):
    """Read-only timestamps returned by the API."""

    created_at: datetime = Field(description="UTC timestamp when the resource was created.")
    updated_at: datetime = Field(description="UTC timestamp when the resource was last updated.")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        """Normalize timestamps to UTC.

        Naive datetimes (e.g. read back from SQLite, which has no timezone-aware
        storage) are interpreted as UTC rather than rejected; PostgreSQL's
        ``timestamptz`` already yields aware values. Either way the output is
        timezone-aware UTC.
        """
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class IdModel(BaseModel):
    """Base model exposing an immutable identifier."""

    id: str = Field(description="Resource identifier (UUID).")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def stringify_id(cls, value: object) -> object:
        """Coerce UUID (and other) identifiers to their string form.

        ORM primary keys are ``uuid.UUID`` objects; the API contract exposes the
        id as a string. Pydantic v2 does not implicitly convert UUID → str, so
        normalize here once for every schema that inherits :class:`IdModel`.
        """
        import uuid as _uuid

        if isinstance(value, _uuid.UUID):
            return str(value)
        return value
