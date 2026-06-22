"""Driver-facing service: phone login, availability, offers, stats, accept/decline.

Backs the mobile app's driver endpoints. Reuses ShipmentService for the assignment
guards so business rules stay in one place.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from math import asin, cos, radians, sin, sqrt
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.enums import ShipmentStatus, UserRole
from app.models.shipment import Shipment
from app.models.user import User
from app.models.warehouse import Warehouse
from app.repositories.driver_repository import DriverRepository
from app.repositories.shipment_repository import ShipmentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.driver_self import DriverStatsRead, ShipmentOfferRead
from app.services.auth_service import AuthService
from app.services.exceptions import NotFoundError
from app.services.shipment_service import ShipmentService


def _haversine_km(
    a: Tuple[Optional[float], Optional[float]],
    b: Tuple[Optional[float], Optional[float]],
) -> Optional[float]:
    """Great-circle distance in km, or None if any coordinate is missing."""
    if None in a or None in b:
        return None
    lat1, lon1, lat2, lon2 = map(radians, [float(a[0]), float(a[1]), float(b[0]), float(b[1])])
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return round(2 * 6371 * asin(sqrt(h)), 1)


class DriverService:
    """Orchestrates driver self-service operations."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._drivers = DriverRepository(session)
        self._users = UserRepository(session)
        self._shipment_repo = ShipmentRepository(session)
        self._shipments = ShipmentService(session)
        self._auth = AuthService(session)

    # ----- auth ----- #
    def login_by_phone(self, phone: str, otp: Optional[str] = None) -> Optional[Tuple[str, Driver]]:
        """Resolve a driver by phone and issue a token.

        OTP verification is intentionally stubbed (returns success for any code);
        wire to an SMS provider in a later increment. Returns (token, driver) or None.
        """
        driver = self._drivers.get_by_phone(phone)
        if driver is None or driver.user is None:
            return None
        user: User = driver.user
        if not user.is_active or user.role != UserRole.DRIVER:
            return None
        token = self._auth.create_access_token(user)
        return token, driver

    # ----- profile / availability ----- #
    def set_availability(self, driver: Driver, is_available: bool) -> Driver:
        driver.is_available = is_available
        self._session.commit()
        self._session.refresh(driver)
        return driver

    # ----- offers ----- #
    def list_nearby_offers(self, driver: Driver, limit: int = 20) -> List[ShipmentOfferRead]:
        """Ready shipments offered to the driver, enriched with city + distance."""
        statement = (
            select(Shipment)
            .where(Shipment.status == ShipmentStatus.READY, Shipment.driver_id.is_(None))
            .limit(limit)
        )
        offers: List[ShipmentOfferRead] = []
        for s in self._session.scalars(statement).all():
            origin: Optional[Warehouse] = s.origin_warehouse
            dest: Optional[Warehouse] = s.destination_warehouse
            distance = (
                _haversine_km(
                    (origin.latitude, origin.longitude),
                    (dest.latitude, dest.longitude),
                )
                if origin and dest
                else None
            )
            offers.append(
                ShipmentOfferRead(
                    id=str(s.id),
                    reference_code=s.reference_code,
                    origin_city=origin.city if origin else None,
                    destination_city=dest.city if dest else None,
                    cargo_type=s.cargo_type,
                    weight_kg=float(s.weight_kg),
                    price_sar=float(s.price_sar) if s.price_sar is not None else None,
                    required_vehicle_label=s.required_vehicle_type,
                    distance_km=distance,
                )
            )
        return offers

    # ----- stats ----- #
    def daily_stats(self, driver: Driver) -> DriverStatsRead:
        """Today's KPIs computed from this driver's delivered shipments.

        earnings/trips are derived from delivered shipments today; distance and
        online_hours require the tracking/session projections (ADR-006) and are
        returned as 0 until those are built.
        """
        now = datetime.now(timezone.utc)
        start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        statement = select(Shipment).where(
            Shipment.driver_id == driver.id,
            Shipment.status == ShipmentStatus.DELIVERED,
            Shipment.delivered_at >= start,
        )
        delivered = list(self._session.scalars(statement).all())
        earnings = sum(float(s.price_sar) for s in delivered if s.price_sar is not None)
        return DriverStatsRead(
            earnings_sar=earnings,
            trips=len(delivered),
            online_hours=0,
            distance_km=0,
            date=now.date(),
        )

    # ----- accept / decline ----- #
    def accept(self, driver: Driver, shipment_id: str) -> Shipment:
        """Driver self-accepts a ready offer (assigns self; vehicle bound later)."""
        return self._shipments.assign_driver_only(shipment_id, str(driver.id))

    def decline(self, driver: Driver, shipment_id: str) -> None:
        """Record a decline. For now validates existence; offer re-queues to others."""
        shipment = self._shipment_repo.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError("Shipment not found.")
        # No state mutation: the offer remains READY and visible to other drivers.
        return None
