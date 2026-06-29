"""Pydantic schemas for authentication flows."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    """Credentials submitted for authentication."""

    email: EmailStr = Field(description="Registered user email.")
    password: str = Field(min_length=8, description="Plaintext password.")
    tenant_slug: Optional[str] = Field(
        default=None,
        description=(
            "Optional tenant slug. Required only when two tenants share the same"
            " email address (multi-tenant deployments). Omit for single-tenant use."
        ),
    )


class RegisterRequest(BaseModel):
    """Payload for self-service organization registration.

    Creates a new tenant and an ADMIN user in a single atomic transaction.
    The resulting admin user can invite further members once logged in.
    """

    email: EmailStr = Field(description="Admin user email address.")
    password: str = Field(min_length=8, description="Plaintext password (min 8 chars).")
    full_name: Optional[str] = Field(default=None, max_length=255, description="Display name.")
    organization_name: str = Field(
        min_length=2,
        max_length=255,
        description="Legal name of the organization.",
    )
    tenant_slug: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
        description=(
            "URL-safe, globally-unique tenant identifier."
            " Lowercase letters, digits, and internal hyphens only."
        ),
    )


class RefreshRequest(BaseModel):
    """Body submitted to the token-refresh endpoint."""

    refresh_token: str = Field(
        description="Opaque refresh token returned by the login or register endpoint."
    )


class LogoutRequest(BaseModel):
    """Optional body for the logout endpoint."""

    refresh_token: Optional[str] = Field(
        default=None,
        description="If provided, the refresh token is immediately revoked in addition to the access token.",
    )


class TokenResponse(BaseModel):
    """Bearer token envelope returned after successful authentication."""

    access_token: str = Field(description="Signed JWT access token.")
    token_type: str = Field(default="bearer", description="Token type for the Authorization header.")
    expires_in: int = Field(description="Access token lifetime in seconds.")
    refresh_token: Optional[str] = Field(
        default=None,
        description="Opaque refresh token for silent renewal. Present in all new login/register responses.",
    )
    user: UserRead = Field(description="Authenticated user context.")
