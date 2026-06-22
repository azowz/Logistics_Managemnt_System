"""CRUD repository for driver profiles."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.repositories.errors import NotFoundError


class DriverRepository:
    """Database access for driver entities; no business logic here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, driver_id: str) -> Optional[Driver]:
        """Return a driver by primary key."""
        try:
            driver_uuid = uuid.UUID(str(driver_id))
        except ValueError:
            return None
        statement = select(Driver).where(Driver.id == driver_uuid)
        return self._session.scalars(statement).first()

    def get_by_user_id(self, user_id: str) -> Optional[Driver]:
        """Return the driver profile owned by a user (one-to-one)."""
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return None
        statement = select(Driver).where(Driver.user_id == user_uuid)
        return self._session.scalars(statement).first()

    def get_by_phone(self, phone_number: str) -> Optional[Driver]:
        """Return a driver by contact phone number (used for phone login)."""
        statement = select(Driver).where(Driver.phone_number == phone_number)
        return self._session.scalars(statement).first()

    def list(self, offset: int = 0, limit: int = 100) -> List[Driver]:
        """List drivers with pagination."""
        statement = select(Driver).offset(offset).limit(limit)
        return list(self._session.scalars(statement).all())

    def create(self, **data) -> Driver:
        """Persist a new driver."""
        driver = Driver(**data)
        self._session.add(driver)
        self._session.commit()
        self._session.refresh(driver)
        return driver

    def update(self, driver_id: str, **data) -> Driver:
        """Update an existing driver; raises if not found."""
        driver = self.get_by_id(driver_id)
        if driver is None:
            raise NotFoundError("Driver not found.")
        for key, value in data.items():
            if value is not None:
                setattr(driver, key, value)
        self._session.commit()
        self._session.refresh(driver)
        return driver

    def delete(self, driver_id: str) -> None:
        """Delete a driver by id; raises if not found."""
        driver = self.get_by_id(driver_id)
        if driver is None:
            raise NotFoundError("Driver not found.")
        self._session.delete(driver)
        self._session.commit()
