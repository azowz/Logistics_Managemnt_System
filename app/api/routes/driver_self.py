"""Driver self-service routes (mobile app contract).

Full paths are declared (no router prefix) and this router is included BEFORE the
generic /drivers and /shipments CRUD routers in main.py so that specific paths
like /drivers/me and /shipments/nearby win over /drivers/{id} and /shipments/{id}.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_driver
from app.core.config import get_settings
from app.db.session import get_session
from app.models.driver import Driver
from app.schemas.driver import DriverRead
from app.schemas.driver_self import (
    AvailabilityUpdate,
    DriverSessionResponse,
    DriverStatsRead,
    PhoneLoginRequest,
    ShipmentOfferRead,
)
from app.schemas.shipment import ShipmentRead
from app.services.driver_service import DriverService
from app.services.exceptions import AssignmentError, NotFoundError, StatusTransitionError

router = APIRouter(tags=["driver-self"])


@router.post(
    "/auth/driver/login",
    response_model=DriverSessionResponse,
    summary="Driver phone login (OTP stubbed); returns token + profile.",
)
def driver_login(payload: PhoneLoginRequest, session: Session = Depends(get_session)) -> DriverSessionResponse:
    service = DriverService(session)
    result = service.login_by_phone(payload.phone, payload.otp)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active driver found for this number.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, driver = result
    settings = get_settings()
    return DriverSessionResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        driver=DriverRead.model_validate(driver),
    )


@router.get("/drivers/me", response_model=DriverRead, summary="Authenticated driver profile.")
def read_me(driver: Driver = Depends(get_current_driver)) -> DriverRead:
    return DriverRead.model_validate(driver)


@router.patch("/drivers/me", response_model=DriverRead, summary="Toggle own availability.")
def update_availability(
    payload: AvailabilityUpdate,
    driver: Driver = Depends(get_current_driver),
    session: Session = Depends(get_session),
) -> DriverRead:
    updated = DriverService(session).set_availability(driver, payload.is_available)
    return DriverRead.model_validate(updated)


@router.get("/drivers/me/stats", response_model=DriverStatsRead, summary="Today's KPIs.")
def read_stats(
    driver: Driver = Depends(get_current_driver),
    session: Session = Depends(get_session),
) -> DriverStatsRead:
    return DriverService(session).daily_stats(driver)


@router.get("/shipments/nearby", response_model=List[ShipmentOfferRead], summary="Ready offers near the driver.")
def nearby(
    driver: Driver = Depends(get_current_driver),
    session: Session = Depends(get_session),
) -> List[ShipmentOfferRead]:
    return DriverService(session).list_nearby_offers(driver)


@router.post("/shipments/{shipment_id}/accept", response_model=ShipmentRead, summary="Driver self-accepts an offer.")
def accept(
    shipment_id: str,
    driver: Driver = Depends(get_current_driver),
    session: Session = Depends(get_session),
) -> ShipmentRead:
    service = DriverService(session)
    try:
        shipment = service.accept(driver, shipment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (AssignmentError, StatusTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ShipmentRead.model_validate(shipment)


@router.post(
    "/shipments/{shipment_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Driver declines an offer.",
)
def decline(
    shipment_id: str,
    driver: Driver = Depends(get_current_driver),
    session: Session = Depends(get_session),
) -> None:
    service = DriverService(session)
    try:
        service.decline(driver, shipment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
