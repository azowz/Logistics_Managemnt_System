"""Repository encapsulating user persistence operations."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.repositories.errors import NotFoundError
from app.models.user import User


class UserRepository:
    """Provides user retrieval helpers."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_email(self, email: str) -> Optional[User]:
        """Return user by email or None if not found."""
        statement = select(User).where(User.email == email)
        return self._session.scalars(statement).first()

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Return user by primary key."""
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return None
        statement = select(User).where(User.id == user_uuid)
        return self._session.scalars(statement).first()

    def create(self, **data) -> User:
        """Persist a new user."""
        user = User(**data)
        self._session.add(user)
        self._session.commit()
        self._session.refresh(user)
        return user

    def update(self, user_id: str, **data) -> User:
        """Update an existing user; raises if not found."""
        user = self.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        for key, value in data.items():
            if value is not None:
                setattr(user, key, value)
        self._session.commit()
        self._session.refresh(user)
        return user

    def delete(self, user_id: str) -> None:
        """Delete a user by id; raises if not found."""
        user = self.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        self._session.delete(user)
        self._session.commit()
