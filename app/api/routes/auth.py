"""Authentication endpoints for issuing and managing JWTs."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token, get_current_user, oauth2_scheme
from app.db.session import get_session
from app.models.user import User
from app.repositories.tenant_repository import TenantRepository
from app.schemas.auth import (
    LogoutRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserRead
from app.services.auth_service import AuthService
from app.services.exceptions import ConflictError, ValidationError

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_token_response(
    user: User,
    access_token: str,
    refresh_token: Optional[str] = None,
) -> TokenResponse:
    """Construct a TokenResponse from authentication artifacts."""
    settings = get_settings()
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_token=refresh_token,
        user=UserRead.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate with email/password and receive JWT.",
)
def login(
    payload: LoginRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    """Authenticate user credentials and return an access + refresh token pair.

    When ``tenant_slug`` is provided the lookup is scoped to that tenant, which
    is required in deployments where two tenants may share the same email.
    """
    auth_service = AuthService(session)

    # Resolve optional tenant_id from slug for scoped login.
    tenant_id: Optional[uuid.UUID] = None
    if payload.tenant_slug:
        tenant = TenantRepository(session).get_by_slug(payload.tenant_slug)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        tenant_id = tenant.id

    user = auth_service.authenticate(
        email=payload.email,
        password=payload.password,
        tenant_id=tenant_id,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, refresh_token = auth_service.issue_token_pair(user)
    return _build_token_response(user, access_token, refresh_token)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new organization and receive credentials.",
)
def register(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    """Create a new tenant and an ADMIN user in a single atomic transaction.

    Returns the same token envelope as :func:`login` so the client can begin
    using the API immediately after registration without a separate login step.
    Raises **409 Conflict** when the ``tenant_slug`` is already taken.
    """
    auth_service = AuthService(session)
    try:
        user, access_token, refresh_token = auth_service.register(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            organization_name=payload.organization_name,
            tenant_slug=payload.tenant_slug,
        )
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return _build_token_response(user, access_token, refresh_token)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange a refresh token for a new token pair.",
)
def refresh_token(
    payload: RefreshRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    """Rotate a refresh token.

    The submitted refresh token is consumed (single-use, atomic GETDEL in
    Redis); a new access + refresh pair is returned.  Returns **401** when the
    token is absent, expired, or has already been consumed.
    """
    auth_service = AuthService(session)
    try:
        user, access_token, new_refresh_token = auth_service.refresh_tokens(
            payload.refresh_token
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return _build_token_response(user, access_token, new_refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current access token.",
)
def logout(
    payload: LogoutRequest,
    current_user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    """Add the current access token's JTI to the Redis denylist.

    Subsequent requests carrying the same access token will receive **401**
    until the token's natural expiry. If ``refresh_token`` is included in the
    body, that token is also revoked immediately.
    """
    token_payload = decode_access_token(token)
    jti: Optional[str] = token_payload.get("jti")
    exp: Optional[int] = token_payload.get("exp")

    AuthService(session).logout(
        jti=jti,
        token_exp_timestamp=exp,
        refresh_token=payload.refresh_token,
    )


@router.get(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Return the authenticated user's profile.",
)
def read_me(current_user: User = Depends(get_current_user)) -> UserRead:
    """Return current authenticated user; useful for client session refresh."""
    return UserRead.model_validate(current_user)
