"""Warehouse CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import UserRole
from app.repositories.errors import NotFoundError
from app.repositories.warehouse_repository import WarehouseRepository
from app.schemas.warehouse import WarehouseCreate, WarehouseRead, WarehouseUpdate

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.post(
    "",
    response_model=WarehouseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a warehouse.",
)
def create_warehouse(
    payload: WarehouseCreate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> WarehouseRead:
    """Create a warehouse."""
    repo = WarehouseRepository(session)
    warehouse = repo.create(**payload.model_dump())
    return WarehouseRead.model_validate(warehouse)


@router.get(
    "/{warehouse_id}",
    response_model=WarehouseRead,
    status_code=status.HTTP_200_OK,
    summary="Get warehouse by ID.",
)
def get_warehouse(
    warehouse_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> WarehouseRead:
    """Fetch a warehouse by ID."""
    repo = WarehouseRepository(session)
    warehouse = repo.get_by_id(warehouse_id)
    if warehouse is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse not found.")
    return WarehouseRead.model_validate(warehouse)


@router.get(
    "",
    response_model=list[WarehouseRead],
    status_code=status.HTTP_200_OK,
    summary="List warehouses.",
)
def list_warehouses(
    offset: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> list[WarehouseRead]:
    """List warehouses with pagination."""
    repo = WarehouseRepository(session)
    items = repo.list(offset=offset, limit=limit)
    return [WarehouseRead.model_validate(w) for w in items]


@router.patch(
    "/{warehouse_id}",
    response_model=WarehouseRead,
    status_code=status.HTTP_200_OK,
    summary="Update a warehouse.",
)
def update_warehouse(
    warehouse_id: str,
    payload: WarehouseUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> WarehouseRead:
    """Update warehouse fields."""
    repo = WarehouseRepository(session)
    try:
        warehouse = repo.update(warehouse_id, **payload.model_dump(exclude_unset=True))
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse not found.")
    return WarehouseRead.model_validate(warehouse)


@router.delete(
    "/{warehouse_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a warehouse.",
)
def delete_warehouse(
    warehouse_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> None:
    """Delete a warehouse by ID."""
    repo = WarehouseRepository(session)
    try:
        repo.delete(warehouse_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse not found.")
