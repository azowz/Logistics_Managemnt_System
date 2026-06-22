"""Authentication service for credential verification and token issuance."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core import security
from app.models.user import User
from app.repositories.user_repository import UserRepository


class AuthService:
    """Handles credential verification and access token creation."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._user_repo = UserRepository(session)
        self._settings = get_settings()

    def authenticate(self, email: str, password: str) -> Optional[User]:
        """Validate user credentials, returning the user on success."""
        user = self._user_repo.get_by_email(email=email)
        if user is None or not user.is_active:
            return None
        if not security.verify_password(password, user.hashed_password):
            return None
        return user

    def create_access_token(self, user: User) -> str:
        """Issue a signed JWT for the authenticated user."""
        expiry = timedelta(minutes=self._settings.access_token_expire_minutes)
        return security.create_access_token(
            subject=str(user.id),
            role=user.role.value,
            expires_delta=expiry,
        )
