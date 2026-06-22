"""Authentication endpoints for issuing and introspecting JWTs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate with email/password and receive JWT.",
)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    """Authenticate user credentials and return a bearer token."""
    auth_service = AuthService(session)
    user = auth_service.authenticate(email=payload.email, password=payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth_service.create_access_token(user)
    settings = get_settings()
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserRead.model_validate(user),
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
