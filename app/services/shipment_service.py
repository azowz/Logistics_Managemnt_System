"""Service layer for shipment lifecycle, assignment, and capacity checks.

This service keeps routes thin by encapsulating business rules:
- Warehouse capacity validation
- Driver/vehicle eligibility and exclusivity
- Shipment status transitions
- Tracking event creation delegation
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.enums import ShipmentStatus, TrackingEventType, UserRole, VehicleStatus
from app.models.shipment import Shipment
from app.models.shipment_tracking_event import ShipmentTrackingEvent
from app.models.vehicle import Vehicle
from app.models.warehouse import Warehouse
from app.repositories.driver_repository import DriverRepository
from app.repositories.shipment_repository import ShipmentRepository
from app.repositories.tracking_event_repository import TrackingEventRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.warehouse_repository import WarehouseRepository
from app.services.exceptions import (
    AssignmentError,
    CapacityError,
    NotFoundError,
    StatusTransitionError,
    TrackingEventError,
)

ACTIVE_STATUSES = {
    ShipmentStatus.CREATED,
    ShipmentStatus.READY,
    ShipmentStatus.ASSIGNED,
    ShipmentStatus.IN_TRANSIT,
}


class ShipmentService:
    """Orchestrates shipment operations with business rules enforced."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._shipments = ShipmentRepository(session)
        self._drivers = DriverRepository(session)
        self._vehicles = VehicleRepository(session)
        self._warehouses = WarehouseRepository(session)
        self._tracking_events = TrackingEventRepository(session)

    # ------------------------- Public API ------------------------- #

    def create_shipment(self, **data) -> Shipment:
        """Create a shipment after validating warehouse capacity."""
        self._assert_warehouses_exist(
            data["origin_warehouse_id"],
            data["destination_warehouse_id"],
        )
        self._assert_capacity(
            warehouse_id=data["origin_warehouse_id"],
            added_weight=float(data["weight_kg"]),
            added_volume=float(data["volume_m3"]),
        )
        self._assert_capacity(
            warehouse_id=data["destination_warehouse_id"],
            added_weight=float(data["weight_kg"]),
            added_volume=float(data["volume_m3"]),
        )
        shipment = self._shipments.create(**data)
        return shipment

    def assign_driver_and_vehicle(
        self,
        shipment_id: str,
        driver_id: str,
        vehicle_id: str,
    ) -> Shipment:
        """Assign driver and vehicle ensuring eligibility and exclusivity."""
        shipment = self._get_existing_shipment(shipment_id)
        driver = self._get_existing_driver(driver_id)
        vehicle = self._get_existing_vehicle(vehicle_id)

        self._validate_driver(driver)
        self._validate_vehicle(vehicle)
        self._assert_driver_not_busy(driver.id, exclude_shipment=shipment.id)
        self._assert_vehicle_not_busy(vehicle.id, exclude_shipment=shipment.id)
        self._assert_vehicle_capacity(vehicle, shipment)

        # Capacity checks on warehouses before moving to ASSIGNED.
        self._assert_capacity(shipment.origin_warehouse_id, float(shipment.weight_kg), float(shipment.volume_m3))
        self._assert_capacity(
            shipment.destination_warehouse_id,
            float(shipment.weight_kg),
            float(shipment.volume_m3),
        )

        now = datetime.now(timezone.utc)
        shipment.driver_id = driver.id
        shipment.vehicle_id = vehicle.id
        shipment.assigned_at = now
        if shipment.status in {ShipmentStatus.CREATED, ShipmentStatus.READY}:
            shipment.status = ShipmentStatus.ASSIGNED

        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    def assign_driver_only(self, shipment_id: str, driver_id: str) -> Shipment:
        """Assign just a driver (self-accept flow); vehicle is assigned later.

        Reuses the same eligibility + exclusivity guards as the full assignment,
        but does not bind a vehicle. The shipment must be in a pre-transit state.
        """
        shipment = self._get_existing_shipment(shipment_id)
        driver = self._get_existing_driver(driver_id)

        self._validate_driver(driver)
        self._assert_driver_not_busy(driver.id, exclude_shipment=shipment.id)

        if shipment.status not in {ShipmentStatus.READY, ShipmentStatus.CREATED}:
            raise AssignmentError("Shipment is not open for acceptance.")

        shipment.driver_id = driver.id
        shipment.assigned_at = datetime.now(timezone.utc)
        shipment.status = ShipmentStatus.ASSIGNED

        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    def transition_status(self, shipment_id: str, new_status: ShipmentStatus) -> Shipment:
        """Transition a shipment to a new status if allowed."""
        shipment = self._get_existing_shipment(shipment_id)
        if not self._is_transition_allowed(shipment.status, new_status):
            raise StatusTransitionError(f"Transition {shipment.status.value} -> {new_status.value} is not allowed.")

        now = datetime.now(timezone.utc)
        shipment.status = new_status
        if new_status == ShipmentStatus.CANCELLED:
            shipment.cancelled_at = now
        elif new_status == ShipmentStatus.DELIVERED:
            shipment.delivered_at = now
        elif new_status == ShipmentStatus.ASSIGNED:
            shipment.assigned_at = now

        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    def create_tracking_event(
        self,
        *,
        shipment_id: str,
        event_type: TrackingEventType,
        status: Optional[ShipmentStatus],
        event_time: datetime,
        latitude: Optional[float],
        longitude: Optional[float],
        notes: Optional[str],
        recorded_by_user_id: Optional[str],
        evidence_url: Optional[str],
    ) -> ShipmentTrackingEvent:
        """Append a tracking event and optionally advance shipment status."""
        shipment = self._get_existing_shipment(shipment_id)
        last_event_time = self._get_latest_event_time(shipment.id)
        if last_event_time and event_time < last_event_time:
            raise TrackingEventError("event_time must be equal or later than the last recorded event.")

        if status is not None and not self._is_transition_allowed(shipment.status, status):
            raise StatusTransitionError(f"Transition {shipment.status.value} -> {status.value} is not allowed.")

        event = ShipmentTrackingEvent(
            shipment_id=shipment.id,
            event_type=event_type,
            status=status,
            event_time=event_time,
            latitude=latitude,
            longitude=longitude,
            notes=notes,
            recorded_by_user_id=recorded_by_user_id,
            evidence_url=evidence_url,
        )
        self._session.add(event)

        # Apply status transition only after event passes validation.
        if status is not None:
            shipment.status = status
            if status == ShipmentStatus.DELIVERED:
                shipment.delivered_at = event_time
            elif status == ShipmentStatus.CANCELLED:
                shipment.cancelled_at = event_time

        self._session.commit()
        self._session.refresh(event)
        return event

    # ------------------------- Internal helpers ------------------------- #

    def _get_existing_shipment(self, shipment_id: str) -> Shipment:
        shipment = self._shipments.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError("Shipment not found.")
        return shipment

    def _get_existing_driver(self, driver_id: str) -> Driver:
        driver = self._drivers.get_by_id(driver_id)
        if driver is None:
            raise NotFoundError("Driver not found.")
        return driver

    def _get_existing_vehicle(self, vehicle_id: str) -> Vehicle:
        vehicle = self._vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle not found.")
        return vehicle

    def _assert_warehouses_exist(self, origin_id: str, destination_id: str) -> None:
        """Ensure both warehouses exist before proceeding."""
        origin = self._warehouses.get_by_id(origin_id)
        dest = self._warehouses.get_by_id(destination_id)
        if origin is None or dest is None:
            raise NotFoundError("Origin or destination warehouse not found.")

    def _assert_capacity(self, warehouse_id: str, added_weight: float, added_volume: float) -> None:
        """Ensure adding a shipment will not exceed warehouse capacity."""
        warehouse = self._warehouses.get_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError("Warehouse not found.")

        current_weight, current_volume = self._current_load_for_warehouse(warehouse_id)
        projected_weight = current_weight + added_weight
        projected_volume = current_volume + added_volume

        if projected_weight > float(warehouse.capacity_weight_kg):
            raise CapacityError("Warehouse weight capacity would be exceeded.")
        if projected_volume > float(warehouse.capacity_volume_m3):
            raise CapacityError("Warehouse volume capacity would be exceeded.")

    def _current_load_for_warehouse(self, warehouse_id: str) -> tuple[float, float]:
        """Calculate active weight and volume reserved for a warehouse."""
        active_statuses = tuple(ACTIVE_STATUSES)
        weight_sum = func.coalesce(func.sum(Shipment.weight_kg), 0)
        volume_sum = func.coalesce(func.sum(Shipment.volume_m3), 0)

        statement = (
            select(weight_sum, volume_sum)
            .where(
                or_(
                    Shipment.origin_warehouse_id == warehouse_id,
                    Shipment.destination_warehouse_id == warehouse_id,
                ),
                Shipment.status.in_(active_statuses),
            )
        )
        weight, volume = self._session.execute(statement).one()
        return float(weight), float(volume)

    def _validate_driver(self, driver: Driver) -> None:
        """Ensure driver is eligible for assignment."""
        # Ensure associated user role is driver.
        if driver.user is None or driver.user.role != UserRole.DRIVER:
            raise AssignmentError("Driver profile is not linked to a driver-role user.")
        if not driver.is_available:
            raise AssignmentError("Driver is marked unavailable for assignments.")

    def _validate_vehicle(self, vehicle: Vehicle) -> None:
        """Ensure vehicle is eligible for assignment."""
        if vehicle.status != VehicleStatus.ACTIVE:
            raise AssignmentError("Vehicle is not active for assignments.")

    def _assert_driver_not_busy(self, driver_id, exclude_shipment) -> None:
        """Prevent assigning a driver already committed to another active shipment."""
        active_statuses = tuple(ACTIVE_STATUSES)
        statement = (
            select(func.count(Shipment.id))
            .where(
                Shipment.driver_id == driver_id,
                Shipment.status.in_(active_statuses),
                Shipment.id != exclude_shipment,
            )
        )
        (count,) = self._session.execute(statement).one()
        if count > 0:
            raise AssignmentError("Driver already assigned to an active shipment.")

    def _assert_vehicle_not_busy(self, vehicle_id, exclude_shipment) -> None:
        """Prevent assigning a vehicle already committed to another active shipment."""
        active_statuses = tuple(ACTIVE_STATUSES)
        statement = (
            select(func.count(Shipment.id))
            .where(
                Shipment.vehicle_id == vehicle_id,
                Shipment.status.in_(active_statuses),
                Shipment.id != exclude_shipment,
            )
        )
        (count,) = self._session.execute(statement).one()
        if count > 0:
            raise AssignmentError("Vehicle already assigned to an active shipment.")

    def _assert_vehicle_capacity(self, vehicle: Vehicle, shipment: Shipment) -> None:
        """Ensure vehicle can carry the shipment."""
        if float(shipment.weight_kg) > float(vehicle.capacity_weight_kg):
            raise AssignmentError("Shipment exceeds vehicle weight capacity.")
        if float(shipment.volume_m3) > float(vehicle.capacity_volume_m3):
            raise AssignmentError("Shipment exceeds vehicle volume capacity.")

    def _is_transition_allowed(self, current: ShipmentStatus, target: ShipmentStatus) -> bool:
        """Validate status transitions according to lifecycle rules."""
        allowed = {
            ShipmentStatus.CREATED: {ShipmentStatus.READY, ShipmentStatus.CANCELLED},
            ShipmentStatus.READY: {ShipmentStatus.ASSIGNED, ShipmentStatus.CANCELLED},
            ShipmentStatus.ASSIGNED: {ShipmentStatus.IN_TRANSIT, ShipmentStatus.CANCELLED},
            ShipmentStatus.IN_TRANSIT: {
                ShipmentStatus.DELIVERED,
                ShipmentStatus.FAILED,
                ShipmentStatus.RETURNED,
            },
            ShipmentStatus.DELIVERED: set(),
            ShipmentStatus.CANCELLED: set(),
            ShipmentStatus.RETURNED: set(),
            ShipmentStatus.FAILED: set(),
        }
        return target in allowed.get(current, set())

    def _get_latest_event_time(self, shipment_id) -> Optional[datetime]:
        """Fetch the most recent tracking event time to enforce ordering."""
        statement = (
            select(ShipmentTrackingEvent.event_time)
            .where(ShipmentTrackingEvent.shipment_id == shipment_id)
            .order_by(ShipmentTrackingEvent.event_time.desc())
            .limit(1)
        )
        result = self._session.execute(statement).first()
        return result[0] if result else None
