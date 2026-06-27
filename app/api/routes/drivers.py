"""Driver CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import UserRole
from app.repositories.driver_repository import DriverRepository
from app.repositories.errors import NotFoundError
from app.schemas.driver import DriverCreate, DriverRead, DriverUpdate

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post(
    "",
    response_model=DriverRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a driver profile.",
)
def create_driver(
    payload: DriverCreate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> DriverRead:
    """Create a driver profile for an existing driver-role user."""
    repo = DriverRepository(session)
    driver = repo.create(**payload.model_dump())
    return DriverRead.model_validate(driver)


@router.get(
    "/{driver_id}",
    response_model=DriverRead,
    status_code=status.HTTP_200_OK,
    summary="Get driver by ID.",
)
def get_driver(
    driver_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> DriverRead:
    """Fetch a driver by ID."""
    repo = DriverRepository(session)
    driver = repo.get_by_id(driver_id)
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found.")
    return DriverRead.model_validate(driver)


@router.get(
    "",
    response_model=list[DriverRead],
    status_code=status.HTTP_200_OK,
    summary="List drivers.",
)
def list_drivers(
    offset: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> list[DriverRead]:
    """List drivers with pagination."""
    repo = DriverRepository(session)
    drivers = repo.list(offset=offset, limit=limit)
    return [DriverRead.model_validate(d) for d in drivers]


@router.patch(
    "/{driver_id}",
    response_model=DriverRead,
    status_code=status.HTTP_200_OK,
    summary="Update a driver.",
)
def update_driver(
    driver_id: str,
    payload: DriverUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> DriverRead:
    """Update driver fields."""
    repo = DriverRepository(session)
    try:
        driver = repo.update(driver_id, **payload.model_dump(exclude_unset=True))
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found.")
    return DriverRead.model_validate(driver)


@router.delete(
    "/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a driver.",
)
def delete_driver(
    driver_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> None:
    """Delete a driver by ID."""
    repo = DriverRepository(session)
    try:
        repo.delete(driver_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found.")
