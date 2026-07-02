"""Equipment & Asset API routes — thin handlers delegating to EquipmentService.

Business logic lives in :class:`~app.services.equipment_service.EquipmentService`.
``/equipment/search`` is declared BEFORE ``/equipment/{id}`` so the literal path
wins over the UUID converter. Domain exceptions are translated centrally by the
global exception handlers.

Role permissions:
  * ADMIN, MANAGER                 → create / update / lifecycle
  * ADMIN, MANAGER, DRIVER         → maintenance start/complete
  * ADMIN, MANAGER, CLIENT, DRIVER → read / list / search
  * ADMIN                          → delete / restore
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.pagination import Page
from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import (
    EquipmentAvailability,
    EquipmentStatus,
    UserRole,
)
from app.schemas.equipment import (
    EquipmentCategoryCreate,
    EquipmentCategoryRead,
    EquipmentCreate,
    EquipmentListParams,
    EquipmentMaintenanceRequest,
    EquipmentModelCreate,
    EquipmentModelRead,
    EquipmentRead,
    EquipmentReserveRequest,
    EquipmentUpdate,
)
from app.services.equipment_service import EquipmentService

router = APIRouter(prefix="/equipment", tags=["equipment"])

_WRITE_ROLES = (UserRole.ADMIN, UserRole.MANAGER)
_FIELD_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.DRIVER)
_READ_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT, UserRole.DRIVER)


def _to_page(page_result) -> Page[EquipmentRead]:
    return Page[EquipmentRead](
        items=[EquipmentRead.model_validate(e) for e in page_result.items],
        total=page_result.total,
        page=page_result.page,
        size=page_result.size,
        pages=page_result.pages,
    )


# --- create ---------------------------------------------------------------


@router.post(
    "",
    response_model=EquipmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new equipment unit (starts active/available).",
)
def create_equipment(
    payload: EquipmentCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentRead:
    svc = EquipmentService(session)
    equipment = svc.create_equipment(**payload.model_dump())
    return EquipmentRead.model_validate(equipment)


# --- categories & models (literal paths declared before /{id}) ------------


@router.post(
    "/categories",
    response_model=EquipmentCategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an equipment category.",
)
def create_category(
    payload: EquipmentCategoryCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentCategoryRead:
    svc = EquipmentService(session)
    return EquipmentCategoryRead.model_validate(svc.create_category(**payload.model_dump()))


@router.get(
    "/categories",
    response_model=list[EquipmentCategoryRead],
    status_code=status.HTTP_200_OK,
    summary="List equipment categories.",
)
def list_categories(
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> list[EquipmentCategoryRead]:
    svc = EquipmentService(session)
    return [EquipmentCategoryRead.model_validate(c) for c in svc.list_categories()]


@router.post(
    "/models",
    response_model=EquipmentModelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an equipment model.",
)
def create_model(
    payload: EquipmentModelCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentModelRead:
    svc = EquipmentService(session)
    return EquipmentModelRead.model_validate(svc.create_model(**payload.model_dump()))


@router.get(
    "/models",
    response_model=list[EquipmentModelRead],
    status_code=status.HTTP_200_OK,
    summary="List equipment models.",
)
def list_models(
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> list[EquipmentModelRead]:
    svc = EquipmentService(session)
    return [EquipmentModelRead.model_validate(m) for m in svc.list_models()]


# --- search (before /{id}) ------------------------------------------------


@router.get(
    "/search",
    response_model=Page[EquipmentRead],
    status_code=status.HTTP_200_OK,
    summary="Search equipment with filters, sorting, and pagination.",
)
def search_equipment(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[EquipmentStatus] = Query(default=None, alias="status"),
    availability_status: Optional[EquipmentAvailability] = Query(default=None),
    category_id: Optional[uuid.UUID] = Query(default=None),
    model_id: Optional[uuid.UUID] = Query(default=None),
    current_warehouse_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> Page[EquipmentRead]:
    params = EquipmentListParams(
        q=q,
        status=status_filter,
        availability_status=availability_status,
        category_id=category_id,
        model_id=model_id,
        current_warehouse_id=current_warehouse_id,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    return _to_page(EquipmentService(session).list_equipment(params))


# --- list -----------------------------------------------------------------


@router.get(
    "",
    response_model=Page[EquipmentRead],
    status_code=status.HTTP_200_OK,
    summary="List equipment with optional filters, sorting, and pagination.",
)
def list_equipment(
    status_filter: Optional[EquipmentStatus] = Query(default=None, alias="status"),
    availability_status: Optional[EquipmentAvailability] = Query(default=None),
    category_id: Optional[uuid.UUID] = Query(default=None),
    model_id: Optional[uuid.UUID] = Query(default=None),
    current_warehouse_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> Page[EquipmentRead]:
    params = EquipmentListParams(
        status=status_filter,
        availability_status=availability_status,
        category_id=category_id,
        model_id=model_id,
        current_warehouse_id=current_warehouse_id,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    return _to_page(EquipmentService(session).list_equipment(params))


# --- retrieve -------------------------------------------------------------


@router.get(
    "/{equipment_id}",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve an equipment unit by ID.",
)
def get_equipment(
    equipment_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> EquipmentRead:
    svc = EquipmentService(session)
    return EquipmentRead.model_validate(
        svc.get_equipment(equipment_id, include_deleted=include_deleted)
    )


# --- update ---------------------------------------------------------------


@router.patch(
    "/{equipment_id}",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Partially update an equipment unit.",
)
def update_equipment(
    equipment_id: uuid.UUID,
    payload: EquipmentUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentRead:
    svc = EquipmentService(session)
    equipment = svc.update_equipment(equipment_id, **payload.model_dump(exclude_unset=True))
    return EquipmentRead.model_validate(equipment)


# --- delete / restore -----------------------------------------------------


@router.delete(
    "/{equipment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an equipment unit.",
)
def delete_equipment(
    equipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN)),
):
    EquipmentService(session).delete_equipment(equipment_id)


@router.post(
    "/{equipment_id}/restore",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Restore a soft-deleted equipment unit.",
)
def restore_equipment(
    equipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN)),
) -> EquipmentRead:
    return EquipmentRead.model_validate(EquipmentService(session).restore_equipment(equipment_id))


# --- lifecycle ------------------------------------------------------------


@router.post(
    "/{equipment_id}/activate",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Activate an equipment unit.",
)
def activate_equipment(
    equipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentRead:
    return EquipmentRead.model_validate(EquipmentService(session).activate_equipment(equipment_id))


@router.post(
    "/{equipment_id}/deactivate",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Deactivate an equipment unit.",
)
def deactivate_equipment(
    equipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentRead:
    return EquipmentRead.model_validate(
        EquipmentService(session).deactivate_equipment(equipment_id)
    )


@router.post(
    "/{equipment_id}/reserve",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Reserve an available equipment unit.",
)
def reserve_equipment(
    equipment_id: uuid.UUID,
    payload: EquipmentReserveRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentRead:
    return EquipmentRead.model_validate(
        EquipmentService(session).reserve_equipment(equipment_id, reference=payload.reference)
    )


@router.post(
    "/{equipment_id}/release",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Release a reserved equipment unit.",
)
def release_equipment(
    equipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentRead:
    return EquipmentRead.model_validate(EquipmentService(session).release_equipment(equipment_id))


@router.post(
    "/{equipment_id}/maintenance/start",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Start maintenance on an equipment unit.",
)
def start_maintenance(
    equipment_id: uuid.UUID,
    payload: EquipmentMaintenanceRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> EquipmentRead:
    return EquipmentRead.model_validate(
        EquipmentService(session).start_maintenance(equipment_id, reason=payload.reason)
    )


@router.post(
    "/{equipment_id}/maintenance/complete",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Complete maintenance on an equipment unit.",
)
def complete_maintenance(
    equipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> EquipmentRead:
    return EquipmentRead.model_validate(
        EquipmentService(session).complete_maintenance(equipment_id)
    )


@router.post(
    "/{equipment_id}/decommission",
    response_model=EquipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Decommission an equipment unit (terminal).",
)
def decommission_equipment(
    equipment_id: uuid.UUID,
    payload: EquipmentMaintenanceRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> EquipmentRead:
    return EquipmentRead.model_validate(
        EquipmentService(session).decommission_equipment(equipment_id, reason=payload.reason)
    )
