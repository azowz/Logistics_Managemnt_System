"""Pydantic schemas for user-related payloads."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import UserRole
from app.schemas.common import IdModel, TimestampMixin


class UserCreate(BaseModel):
    """Payload for creating a new user."""

    email: EmailStr = Field(description="Unique email for login and contact.")
    full_name: Optional[str] = Field(default=None, description="Display name of the user.")
    password: str = Field(min_length=8, description="Plaintext password; will be hashed server-side.")
    role: UserRole = Field(description="Role defining permissions.")


class UserUpdate(BaseModel):
    """Mutable fields for updating an existing user."""

    full_name: Optional[str] = Field(default=None, description="Updated display name.")
    password: Optional[str] = Field(default=None, min_length=8, description="New password if rotation is needed.")
    is_active: Optional[bool] = Field(default=None, description="Activate or deactivate the account.")

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: Optional[str]) -> Optional[str]:
        """Ensure password is not empty when provided."""
        if value is not None and not value.strip():
            raise ValueError("Password cannot be blank.")
        return value


class UserRead(IdModel, TimestampMixin):
    """Representation of a user returned from API."""

    email: EmailStr
    full_name: Optional[str] = None
    role: UserRole
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
