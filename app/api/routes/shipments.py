"""Shipment routes exposing thin handlers over the service layer."""

from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import UserRole
from app.repositories.errors import NotFoundError as RepoNotFoundError
from app.repositories.shipment_repository import ShipmentRepository
from app.repositories.tracking_event_repository import TrackingEventRepository
from app.schemas.shipment import ShipmentCreate, ShipmentRead, ShipmentUpdate, ShipmentWithEvents
from app.schemas.shipment_actions import AssignmentRequest, StatusUpdateRequest
from app.schemas.tracking_event import TrackingEventCreate, TrackingEventRead
from app.services.exceptions import (
    AssignmentError,
    CapacityError,
    NotFoundError,
    StatusTransitionError,
    TrackingEventError,
)
from app.services.shipment_service import ShipmentService

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.post(
    "",
    response_model=ShipmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shipment.",
)
def create_shipment(
    payload: ShipmentCreate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> ShipmentRead:
    """Create a shipment after capacity validation."""
    service = ShipmentService(session)
    try:
        shipment = service.create_shipment(**payload.model_dump())
    except (CapacityError, NotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ShipmentRead.model_validate(shipment)


@router.get(
    "",
    response_model=List[ShipmentRead],
    status_code=status.HTTP_200_OK,
    summary="List shipments.",
)
def list_shipments(
    offset: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> List[ShipmentRead]:
    """List shipments with pagination."""
    repo = ShipmentRepository(session)
    shipments = repo.list(offset=offset, limit=limit)
    return [ShipmentRead.model_validate(s) for s in shipments]


@router.get(
    "/{shipment_id}",
    response_model=ShipmentWithEvents,
    status_code=status.HTTP_200_OK,
    summary="Get a shipment with tracking history.",
)
def get_shipment(
    shipment_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> ShipmentWithEvents:
    """Retrieve a shipment and its ordered tracking events."""
    shipment_repo = ShipmentRepository(session)
    tracking_repo = TrackingEventRepository(session)
    shipment = shipment_repo.get_by_id(shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found.")
    events = tracking_repo.list_for_shipment(shipment_id)
    shipment_dict = ShipmentWithEvents.model_validate(shipment).model_dump()
    shipment_dict["tracking_events"] = [TrackingEventRead.model_validate(e) for e in events]
    return ShipmentWithEvents.model_validate(shipment_dict)


@router.patch(
    "/{shipment_id}",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Update shipment fields (non-lifecycle).",
)
def update_shipment(
    shipment_id: str,
    payload: ShipmentUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> ShipmentRead:
    """Update mutable shipment fields; service handles validation."""
    repo = ShipmentRepository(session)
    shipment = repo.get_by_id(shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found.")
    data = payload.model_dump(exclude_unset=True)
    try:
        shipment = repo.update(shipment_id, **data)
    except RepoNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found.")
    return ShipmentRead.model_validate(shipment)


@router.post(
    "/{shipment_id}/assign",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Assign driver and vehicle to a shipment.",
)
def assign_shipment(
    shipment_id: str,
    payload: AssignmentRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> ShipmentRead:
    """Assign driver and vehicle with capacity and availability checks."""
    service = ShipmentService(session)
    try:
        shipment = service.assign_driver_and_vehicle(
            shipment_id=shipment_id,
            driver_id=payload.driver_id,
            vehicle_id=payload.vehicle_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (AssignmentError, CapacityError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ShipmentRead.model_validate(shipment)


@router.post(
    "/{shipment_id}/status",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
    summary="Transition shipment status.",
)
def transition_status(
    shipment_id: str,
    payload: StatusUpdateRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> ShipmentRead:
    """Apply a status transition following lifecycle rules."""
    service = ShipmentService(session)
    try:
        shipment = service.transition_status(shipment_id, payload.status)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except StatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ShipmentRead.model_validate(shipment)


@router.post(
    "/{shipment_id}/events",
    response_model=TrackingEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Append a tracking event to a shipment.",
)
def create_tracking_event(
    shipment_id: str,
    payload: TrackingEventCreate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER, UserRole.DRIVER)),
) -> TrackingEventRead:
    """Append a tracking event; enforces chronological order and optional status change."""
    service = ShipmentService(session)
    body = payload.model_dump()
    # Override shipment_id from path to avoid mismatches.
    body["shipment_id"] = shipment_id
    try:
        event = service.create_tracking_event(**body)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (StatusTransitionError, TrackingEventError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return TrackingEventRead.model_validate(event)
