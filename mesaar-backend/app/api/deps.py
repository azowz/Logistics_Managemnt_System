"""Shared FastAPI dependencies.

* :func:`get_current_driver` -- resolves the :class:`~app.models.driver.Driver`
  profile for an authenticated driver-role user.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_session
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.driver_repository import DriverRepository


def get_current_driver(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Driver:
    """Resolve the Driver profile for the authenticated driver-role user."""
    if user.role != UserRole.DRIVER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is for drivers only.",
        )
    driver = DriverRepository(session).get_by_user_id(str(user.id))
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No driver profile linked to this account.",
        )
    return driver


__all__ = ["get_current_driver"]
