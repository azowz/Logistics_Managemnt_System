"""Pydantic schemas for authentication flows."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    """Credentials submitted for authentication."""

    email: EmailStr = Field(description="Registered user email.")
    password: str = Field(min_length=8, description="Plaintext password.")


class TokenResponse(BaseModel):
    """Bearer token returned after successful authentication."""

    access_token: str = Field(description="JWT access token.")
    token_type: str = Field(default="bearer", description="Token type for Authorization header.")
    expires_in: int = Field(description="Token lifetime in seconds.")
    user: UserRead = Field(description="Authenticated user context.")
