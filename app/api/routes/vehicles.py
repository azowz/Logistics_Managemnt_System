"""Vehicle CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import UserRole
from app.repositories.errors import NotFoundError
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate, VehicleRead, VehicleUpdate

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.post(
    "",
    response_model=VehicleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vehicle.",
)
def create_vehicle(
    payload: VehicleCreate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> VehicleRead:
    """Create a vehicle."""
    repo = VehicleRepository(session)
    vehicle = repo.create(**payload.model_dump())
    return VehicleRead.model_validate(vehicle)


@router.get(
    "/{vehicle_id}",
    response_model=VehicleRead,
    status_code=status.HTTP_200_OK,
    summary="Get vehicle by ID.",
)
def get_vehicle(
    vehicle_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> VehicleRead:
    """Fetch vehicle by ID."""
    repo = VehicleRepository(session)
    vehicle = repo.get_by_id(vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found.")
    return VehicleRead.model_validate(vehicle)


@router.get(
    "",
    response_model=list[VehicleRead],
    status_code=status.HTTP_200_OK,
    summary="List vehicles.",
)
def list_vehicles(
    offset: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> list[VehicleRead]:
    """List vehicles with pagination."""
    repo = VehicleRepository(session)
    vehicles = repo.list(offset=offset, limit=limit)
    return [VehicleRead.model_validate(v) for v in vehicles]


@router.patch(
    "/{vehicle_id}",
    response_model=VehicleRead,
    status_code=status.HTTP_200_OK,
    summary="Update a vehicle.",
)
def update_vehicle(
    vehicle_id: str,
    payload: VehicleUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> VehicleRead:
    """Update vehicle fields."""
    repo = VehicleRepository(session)
    try:
        vehicle = repo.update(vehicle_id, **payload.model_dump(exclude_unset=True))
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found.")
    return VehicleRead.model_validate(vehicle)


@router.delete(
    "/{vehicle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a vehicle.",
)
def delete_vehicle(
    vehicle_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> None:
    """Delete a vehicle by ID."""
    repo = VehicleRepository(session)
    try:
        repo.delete(vehicle_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found.")
