"""Shipment API routes — thin HTTP handlers delegating to ShipmentService.

All business logic lives in :class:`~app.services.shipment_service.ShipmentService`.
These handlers extract/validate HTTP inputs, enforce RBAC via
:func:`~app.core.security.require_roles`, and let the global exception handlers
translate domain exceptions to HTTP responses.

Route ordering note: ``/shipments/search`` is declared BEFORE ``/shipments/{id}``
so the literal path wins over the UUID path converter.

Role permissions:
  * ADMIN, MANAGER                 → create / update / lifecycle / assign
  * ADMIN, MANAGER, DRIVER         → pickup / transit / delay / deliver / fail / tracking
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
from app.models.enums import ShipmentPriority, ShipmentStatus, UserRole
from app.schemas.shipment import (
    ShipmentAssignRequest,
    ShipmentCancelRequest,
    ShipmentCreate,
    ShipmentDelayRequest,
    ShipmentFailRequest,
    ShipmentListParams,
    ShipmentRead,
    ShipmentReturnRequest,
    ShipmentUpdate,
)
from app.schemas.tracking_event import TrackingEventCreate, TrackingEventRead
from app.services.shipment_service import ShipmentService

router = APIRouter(prefix="/shipments", tags=["shipments"])

_WRITE_ROLES = (UserRole.ADMIN, UserRole.MANAGER)
_FIELD_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.DRIVER)
_READ_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT, UserRole.DRIVER)


def _to_page(page_result) -> Page[ShipmentRead]:
    """Map a service Page[Shipment] to a Page[ShipmentRead] response envelope."""
    return Page[ShipmentRead](
        items=[ShipmentRead.model_validate(s) for s in page_result.items],
        total=page_result.total,
        page=page_result.page,
        size=page_result.size,
        pages=page_result.pages,
    )


# ---------------------------------------------------------------------------
# POST /shipments — create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ShipmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new shipment (starts in created).",
)
def create_shipment(
    payload: ShipmentCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> ShipmentRead:
    """Create a shipment for the current tenant; **409** on duplicate reference,
    **422** when a related aggregate is missing/cross-tenant."""
    svc = ShipmentService(session)
    shipment = svc.create_shipment(**payload.model_dump())
    return ShipmentRead.model_validate(shipment)


# ---------------------------------------------------------------------------
# GET /shipments/search — declared before /{id}
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=Page[ShipmentRead],
    status_code=status.HTTP_200_OK,
    summary="Search shipments with filters, sorting, and pagination.",
)
def search_shipments(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[ShipmentStatus] = Query(default=None, alias="status"),
    priority: Optional[ShipmentPriority] = Query(default=None),
    driver_id: Optional[uuid.UUID] = Query(default=None),
    vehicle_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    client_id: Optional[uuid.UUID] = Query(default=None),
    origin_warehouse_id: Optional[uuid.UUID] = Query(default=None),
    destination_warehouse_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> Page[ShipmentRead]:
    """Faceted + free-text (``q`` over reference/cargo) search across the tenant."""
    params = ShipmentListParams(
        q=q,
        status=status_filter,
        priority=priority,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        order_id=order_id,
        client_id=client_id,
        origin_warehouse_id=origin_warehouse_id,
        destination_warehouse_id=destination_warehouse_id,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    return _to_page(ShipmentService(session).list_shipments(params))


# ---------------------------------------------------------------------------
# GET /shipments — list
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=Page[ShipmentRead],
    status_code=status.HTTP_200_OK,
    summary="List shipments with optional filters, sorting, and pagination.",
)
def list_shipments(
    status_filter: Optional[ShipmentStatus] = Query(default=None, alias="status"),
    priority: Optional[ShipmentPriority] = Query(default=None),
    driver_id: Optional[uuid.UUID] = Query(default=None),
    vehicle_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    client_id: Optional[uuid.UUID] = Query(default=None),
    origin_warehouse_id: Optional[uuid.UUID] = Query(default=None),
    destination_warehouse_id: Optional[uuid.UUID] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> Page[ShipmentRead]:
    """Return a paginated list of shipments visible to the current tenant."""
    params = ShipmentListParams(
        status=status_filter,
        priority=priority,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        order_id=order_id,
        client_id=client_id,
        origin_warehouse_id=origin_warehouse_id,
        destination_warehouse_id=destination_warehouse_id,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        size=size,
    )
    return _to_page(ShipmentService(session).list_shipments(params))


# ---------------------------------------------------------------------------
# GET /shipments/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/{shipment_id}",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a shipment by ID.",
)
def get_shipment(
    shipment_id: uuid.UUID,
    include_deleted: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_READ_ROLES)),
) -> ShipmentRead:
    """Fetch a single shipment; **404** when not found or soft-deleted."""
    svc = ShipmentService(session)
    return ShipmentRead.model_validate(
        svc.get_shipment(shipment_id, include_deleted=include_deleted)
    )


# ---------------------------------------------------------------------------
# PATCH /shipments/{id}
# ---------------------------------------------------------------------------


@router.patch(
    "/{shipment_id}",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Partially update a shipment (non-lifecycle fields).",
)
def update_shipment(
    shipment_id: uuid.UUID,
    payload: ShipmentUpdate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> ShipmentRead:
    """Apply a partial update. Terminal shipments cannot be edited (**422**)."""
    svc = ShipmentService(session)
    shipment = svc.update_shipment(shipment_id, **payload.model_dump(exclude_unset=True))
    return ShipmentRead.model_validate(shipment)


# ---------------------------------------------------------------------------
# DELETE /shipments/{id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{shipment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a shipment.",
)
def delete_shipment(
    shipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN)),
):
    """Logically remove a shipment (soft-delete). **404** when not found."""
    ShipmentService(session).delete_shipment(shipment_id)


@router.post(
    "/{shipment_id}/restore",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Restore a soft-deleted shipment.",
)
def restore_shipment(
    shipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(UserRole.ADMIN)),
) -> ShipmentRead:
    """Undo a soft-delete. **404** when missing, **422** when not deleted."""
    return ShipmentRead.model_validate(ShipmentService(session).restore_shipment(shipment_id))


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


@router.post(
    "/{shipment_id}/ready",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Mark a shipment ready for assignment.",
)
def ready_shipment(
    shipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> ShipmentRead:
    """created → ready."""
    return ShipmentRead.model_validate(ShipmentService(session).mark_ready(shipment_id))


@router.post(
    "/{shipment_id}/assign",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Assign a driver and vehicle to a ready shipment.",
)
def assign_shipment(
    shipment_id: uuid.UUID,
    payload: ShipmentAssignRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> ShipmentRead:
    """ready → assigned (requires an available driver and vehicle)."""
    svc = ShipmentService(session)
    shipment = svc.assign_shipment(
        shipment_id,
        driver_id=payload.driver_id,
        vehicle_id=payload.vehicle_id,
        reason=payload.reason,
    )
    return ShipmentRead.model_validate(shipment)


@router.post(
    "/{shipment_id}/pickup",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Mark cargo picked up.",
)
def pickup_shipment(
    shipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> ShipmentRead:
    """assigned → picked_up."""
    return ShipmentRead.model_validate(ShipmentService(session).pickup_shipment(shipment_id))


@router.post(
    "/{shipment_id}/transit",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Start transit (also resumes a delayed shipment).",
)
def transit_shipment(
    shipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> ShipmentRead:
    """picked_up/delayed → in_transit."""
    return ShipmentRead.model_validate(ShipmentService(session).start_transit(shipment_id))


@router.post(
    "/{shipment_id}/delay",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Flag an in-transit shipment as delayed.",
)
def delay_shipment(
    shipment_id: uuid.UUID,
    payload: ShipmentDelayRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> ShipmentRead:
    """in_transit → delayed."""
    return ShipmentRead.model_validate(
        ShipmentService(session).mark_delayed(shipment_id, reason=payload.reason)
    )


@router.post(
    "/{shipment_id}/deliver",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Mark a shipment delivered.",
)
def deliver_shipment(
    shipment_id: uuid.UUID,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> ShipmentRead:
    """in_transit/delayed → delivered."""
    return ShipmentRead.model_validate(ShipmentService(session).deliver_shipment(shipment_id))


@router.post(
    "/{shipment_id}/fail",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Mark a shipment as failed.",
)
def fail_shipment(
    shipment_id: uuid.UUID,
    payload: ShipmentFailRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> ShipmentRead:
    """in-progress → failed."""
    return ShipmentRead.model_validate(
        ShipmentService(session).fail_shipment(shipment_id, reason=payload.reason)
    )


@router.post(
    "/{shipment_id}/return",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Return a shipment to origin.",
)
def return_shipment(
    shipment_id: uuid.UUID,
    payload: ShipmentReturnRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> ShipmentRead:
    """in_transit/delayed/failed → returned."""
    return ShipmentRead.model_validate(
        ShipmentService(session).return_shipment(shipment_id, reason=payload.reason)
    )


@router.post(
    "/{shipment_id}/cancel",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Cancel a shipment (compensation flagged when in progress).",
)
def cancel_shipment(
    shipment_id: uuid.UUID,
    payload: ShipmentCancelRequest,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_WRITE_ROLES)),
) -> ShipmentRead:
    """any pre-delivery → cancelled."""
    return ShipmentRead.model_validate(
        ShipmentService(session).cancel_shipment(shipment_id, reason=payload.reason)
    )


# ---------------------------------------------------------------------------
# Tracking events (preserved — append-only history ingestion)
# ---------------------------------------------------------------------------


@router.post(
    "/{shipment_id}/events",
    response_model=TrackingEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Append a tracking event to a shipment.",
)
def create_tracking_event(
    shipment_id: uuid.UUID,
    payload: TrackingEventCreate,
    session: Session = Depends(get_session),
    current_user=Depends(require_roles(*_FIELD_ROLES)),
) -> TrackingEventRead:
    """Append a tracking event; enforces chronological order and optional status change."""
    svc = ShipmentService(session)
    body = payload.model_dump()
    body["shipment_id"] = str(shipment_id)  # path wins over body
    event = svc.create_tracking_event(**body)
    return TrackingEventRead.model_validate(event)
