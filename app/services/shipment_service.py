"""Service layer for the Shipment aggregate (Sprint 5 refactor).

Production-grade domain service following the Customer/Order pattern:

  * Service owns the Unit of Work — every state-changing op ends in a single
    ``session.commit()``; the repository never commits.
  * Every state change emits domain events into the transactional outbox in the
    same transaction (flush → append → commit).
  * Tenant context comes from :mod:`app.db.tenant` (never from the client).
  * Cross-tenant assignment is rejected (driver/vehicle/warehouse/order/client).
  * Lifecycle transitions are validated by
    :class:`~app.services.shipment_policies.ShipmentStateMachine`.

Legacy entry points used elsewhere are preserved with compatible signatures:
``create_shipment``, ``assign_driver_and_vehicle``, ``assign_driver_only``
(driver self-accept), ``transition_status``, and ``create_tracking_event``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.shipment_events import (
    ShipmentAddressChanged,
    ShipmentAssigned,
    ShipmentCancelled,
    ShipmentCargoChanged,
    ShipmentCreated,
    ShipmentDelayed,
    ShipmentDeleted,
    ShipmentDelivered,
    ShipmentDriverChanged,
    ShipmentFailed,
    ShipmentInTransit,
    ShipmentMarkedReady,
    ShipmentPickedUp,
    ShipmentRestored,
    ShipmentReturned,
    ShipmentStatusChanged,
    ShipmentUpdated,
    ShipmentVehicleChanged,
)
from app.models.driver import Driver
from app.models.enums import ShipmentStatus, TrackingEventType, UserRole, VehicleStatus
from app.models.shipment import Shipment
from app.models.shipment_tracking_event import ShipmentTrackingEvent
from app.models.vehicle import Vehicle
from app.repositories.driver_repository import DriverRepository
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.shipment_repository import ShipmentRepository
from app.repositories.tracking_event_repository import TrackingEventRepository
from app.repositories.user_repository import UserRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.warehouse_repository import WarehouseRepository
from app.schemas.shipment import ShipmentListParams
from app.services.exceptions import (
    AssignmentError,
    CapacityError,
    ConflictError,
    NotFoundError,
    StatusTransitionError,
    TrackingEventError,
    ValidationError,
)
from app.services.shipment_policies import ShipmentStateMachine

_AGGREGATE_TYPE = "Shipment"

# Statuses that reserve warehouse / driver / vehicle capacity.
ACTIVE_STATUSES = {
    ShipmentStatus.CREATED,
    ShipmentStatus.READY,
    ShipmentStatus.ASSIGNED,
    ShipmentStatus.PICKED_UP,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.DELAYED,
}

# Fields whose change emits a fine-grained event.
_ADDRESS_FIELDS = frozenset({"origin_warehouse_id", "destination_warehouse_id"})
_CARGO_FIELDS = frozenset(
    {"cargo_type", "cargo_description", "weight_kg", "volume_m3", "required_vehicle_type"}
)


class ShipmentService:
    """Orchestrates shipment lifecycle, assignment, capacity, and events."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._shipments = ShipmentRepository(session)
        self._drivers = DriverRepository(session)
        self._vehicles = VehicleRepository(session)
        self._warehouses = WarehouseRepository(session)
        self._tracking_events = TrackingEventRepository(session)
        self._orders = OrderRepository(session)
        self._users = UserRepository(session)
        self._event_repo = EventStoreRepository(session)

    # ------------------------------------------------------------------
    # Context + event helpers
    # ------------------------------------------------------------------

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self) -> Optional[uuid.UUID]:
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        next_version = self._event_repo.next_aggregate_version(aggregate_id)
        envelope = EventEnvelope.create(
            event,
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_version=next_version,
            aggregate_type=_AGGREGATE_TYPE,
            user_id=self._actor_id(),
        )
        self._event_repo.append(envelope)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_shipment(self, **data) -> Shipment:
        """Create a shipment after validating tenant ownership and capacity.

        Raises:
            :exc:`ValidationError`: missing tenant / client / order not in tenant.
            :exc:`ConflictError`: duplicate reference code in the tenant.
            :exc:`NotFoundError`: warehouse missing.
            :exc:`CapacityError`: warehouse capacity would be exceeded.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        reference_code = data.get("reference_code")
        if reference_code and self._shipments.get_by_reference_code(reference_code):
            raise ConflictError(
                f"Shipment reference '{reference_code}' already exists in this tenant."
            )

        # --- cross-tenant ownership validation ---
        self._assert_user_in_tenant(data.get("client_id"), tenant_id, label="Client")
        if data.get("order_id"):
            self._assert_order_in_tenant(data["order_id"], tenant_id)
        self._assert_warehouses_exist(
            data["origin_warehouse_id"], data["destination_warehouse_id"]
        )

        self._assert_capacity(
            data["origin_warehouse_id"], float(data["weight_kg"]), float(data["volume_m3"])
        )
        self._assert_capacity(
            data["destination_warehouse_id"], float(data["weight_kg"]), float(data["volume_m3"])
        )

        data.pop("status", None)  # always starts CREATED
        shipment = self._shipments.create(
            tenant_id=tenant_id,
            status=ShipmentStatus.CREATED,
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()

        self._emit(
            ShipmentCreated(
                shipment_id=shipment.id,
                tenant_id=tenant_id,
                reference_code=shipment.reference_code,
                client_id=shipment.client_id,
                order_id=shipment.order_id,
                origin_warehouse_id=shipment.origin_warehouse_id,
                destination_warehouse_id=shipment.destination_warehouse_id,
                status=shipment.status.value,
                priority=shipment.priority.value,
            ),
            aggregate_id=shipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_shipment(self, shipment_id, *, include_deleted: bool = False) -> Shipment:
        shipment = self._shipments.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        if shipment.is_deleted and not include_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        return shipment

    def list_shipments(self, params: ShipmentListParams) -> Page[Shipment]:
        items, total = self._shipments.list_shipments(
            q=params.q,
            status=params.status,
            priority=params.priority,
            client_id=params.client_id,
            driver_id=params.driver_id,
            vehicle_id=params.vehicle_id,
            order_id=params.order_id,
            origin_warehouse_id=params.origin_warehouse_id,
            destination_warehouse_id=params.destination_warehouse_id,
            include_deleted=params.include_deleted,
            sort_by=params.sort_by,
            sort_dir=params.sort_dir,
            limit=params.size,
            offset=params.offset,
        )
        pp = PageParams(page=params.page, size=params.size)
        return Page.create(items=items, total=total, params=pp)

    # search is a thin alias so the API surface matches Customer/Order.
    search_shipments = list_shipments

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_shipment(self, shipment_id, **data) -> Shipment:
        """Apply partial, non-lifecycle updates with fine-grained events."""
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._shipments.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found (deleted).")
        if ShipmentStateMachine.is_terminal(shipment.status):
            raise ValidationError(
                f"Shipment {shipment_id} is terminal ('{shipment.status.value}') and cannot be edited."
            )

        # Reference uniqueness on change.
        new_ref = data.get("reference_code")
        if new_ref and new_ref != shipment.reference_code:
            existing = self._shipments.get_by_reference_code(new_ref)
            if existing and existing.id != shipment.id:
                raise ConflictError(f"Shipment reference '{new_ref}' already in use.")

        # Validate warehouse changes stay in-tenant.
        for wh_field in ("origin_warehouse_id", "destination_warehouse_id"):
            if data.get(wh_field):
                self._assert_warehouse_in_tenant(data[wh_field], tenant_id)

        applied = {k: v for k, v in data.items() if v is not None}
        address_changes = {k: v for k, v in applied.items() if k in _ADDRESS_FIELDS}
        cargo_changes = {k: v for k, v in applied.items() if k in _CARGO_FIELDS}
        other_changes = {
            k: v
            for k, v in applied.items()
            if k not in _ADDRESS_FIELDS and k not in _CARGO_FIELDS
        }

        data["updated_by"] = actor_id
        self._shipments.update(shipment, **data)
        self._session.flush()

        if address_changes:
            self._emit(
                ShipmentAddressChanged(
                    shipment_id=shipment.id, tenant_id=tenant_id,
                    changed_fields=_jsonable(address_changes),
                ),
                aggregate_id=shipment.id, tenant_id=tenant_id,
            )
        if cargo_changes:
            self._emit(
                ShipmentCargoChanged(
                    shipment_id=shipment.id, tenant_id=tenant_id,
                    changed_fields=_jsonable(cargo_changes),
                ),
                aggregate_id=shipment.id, tenant_id=tenant_id,
            )
        if other_changes:
            self._emit(
                ShipmentUpdated(
                    shipment_id=shipment.id, tenant_id=tenant_id,
                    changed_fields=_jsonable(other_changes),
                ),
                aggregate_id=shipment.id, tenant_id=tenant_id,
            )

        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def delete_shipment(self, shipment_id) -> None:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._shipments.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} is already deleted.")

        self._shipments.soft_delete(shipment, deleted_by=actor_id)
        shipment.updated_by = actor_id
        self._session.flush()
        self._emit(
            ShipmentDeleted(shipment_id=shipment.id, tenant_id=tenant_id, deleted_by=actor_id),
            aggregate_id=shipment.id, tenant_id=tenant_id,
        )
        self._session.commit()

    def restore_shipment(self, shipment_id) -> Shipment:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._shipments.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        if not shipment.is_deleted:
            raise ValidationError(f"Shipment {shipment_id} is not deleted; nothing to restore.")

        self._shipments.restore(shipment)
        shipment.updated_by = actor_id
        self._session.flush()
        self._emit(
            ShipmentRestored(shipment_id=shipment.id, tenant_id=tenant_id),
            aggregate_id=shipment.id, tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    # ------------------------------------------------------------------
    # Transition core
    # ------------------------------------------------------------------

    def _transition(
        self,
        shipment_id,
        new_status: ShipmentStatus,
        *,
        reason: Optional[str] = None,
        mutate: Optional[Callable[[Shipment], None]] = None,
        extra_events: Optional[List[Callable[[Shipment, ShipmentStatus], object]]] = None,
    ) -> Shipment:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._shipments.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found (deleted).")

        previous = shipment.status
        if new_status == previous:
            return shipment  # idempotent

        ShipmentStateMachine.validate_transition(previous, new_status)

        if mutate is not None:
            mutate(shipment)
        shipment.status = new_status
        shipment.updated_by = actor_id
        self._session.flush()

        for factory in extra_events or []:
            self._emit(factory(shipment, previous), aggregate_id=shipment.id, tenant_id=tenant_id)
        self._emit(
            ShipmentStatusChanged(
                shipment_id=shipment.id, tenant_id=tenant_id,
                previous_status=previous.value, new_status=new_status.value, reason=reason,
            ),
            aggregate_id=shipment.id, tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    def mark_ready(self, shipment_id) -> Shipment:
        """created → ready."""
        return self._transition(
            shipment_id, ShipmentStatus.READY,
            extra_events=[
                lambda s, prev: ShipmentMarkedReady(
                    shipment_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value
                )
            ],
        )

    def assign_shipment(
        self, shipment_id, *, driver_id, vehicle_id, reason: Optional[str] = None
    ) -> Shipment:
        """Assign driver AND vehicle (formal dispatch): ready → assigned."""
        tenant_id = self._tenant_id()
        shipment = self._shipments.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found (deleted).")
        if shipment.status not in {ShipmentStatus.CREATED, ShipmentStatus.READY}:
            raise StatusTransitionError(
                f"Cannot assign a shipment in status '{shipment.status.value}'."
            )

        driver = self._require_driver(driver_id, tenant_id)
        vehicle = self._require_vehicle(vehicle_id, tenant_id)
        self._validate_driver(driver)
        self._validate_vehicle(vehicle)
        self._assert_driver_not_busy(driver.id, exclude=shipment.id)
        self._assert_vehicle_not_busy(vehicle.id, exclude=shipment.id)
        self._assert_vehicle_capacity(vehicle, shipment)

        prev_driver = shipment.driver_id
        prev_vehicle = shipment.vehicle_id

        def _mutate(s: Shipment) -> None:
            s.driver_id = driver.id
            s.vehicle_id = vehicle.id
            s.assigned_at = utcnow()

        return self._transition(
            shipment_id, ShipmentStatus.ASSIGNED, reason=reason, mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentAssigned(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    driver_id=s.driver_id, vehicle_id=s.vehicle_id, previous_status=prev.value,
                ),
                lambda s, prev: ShipmentDriverChanged(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    previous_driver_id=prev_driver, new_driver_id=s.driver_id,
                ),
                lambda s, prev: ShipmentVehicleChanged(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    previous_vehicle_id=prev_vehicle, new_vehicle_id=s.vehicle_id,
                ),
            ],
        )

    def pickup_shipment(self, shipment_id) -> Shipment:
        """assigned → picked_up (requires a bound driver)."""
        shipment = self._shipments.get_by_id_or_raise(shipment_id)
        if not shipment.is_deleted and shipment.driver_id is None:
            raise AssignmentError("Cannot pick up a shipment with no assigned driver.")

        def _mutate(s: Shipment) -> None:
            s.picked_up_at = utcnow()

        return self._transition(
            shipment_id, ShipmentStatus.PICKED_UP, mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentPickedUp(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    picked_up_at=s.picked_up_at.isoformat() if s.picked_up_at else None,
                    previous_status=prev.value,
                )
            ],
        )

    def start_transit(self, shipment_id) -> Shipment:
        """picked_up/delayed → in_transit."""
        return self._transition(
            shipment_id, ShipmentStatus.IN_TRANSIT,
            extra_events=[
                lambda s, prev: ShipmentInTransit(
                    shipment_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value
                )
            ],
        )

    def mark_delayed(self, shipment_id, *, reason: Optional[str] = None) -> Shipment:
        """picked_up/in_transit → delayed (overlay)."""
        return self._transition(
            shipment_id, ShipmentStatus.DELAYED, reason=reason,
            extra_events=[
                lambda s, prev: ShipmentDelayed(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    previous_status=prev.value, reason=reason,
                )
            ],
        )

    def deliver_shipment(self, shipment_id) -> Shipment:
        """in_transit/delayed → delivered (terminal)."""
        def _mutate(s: Shipment) -> None:
            s.delivered_at = utcnow()

        return self._transition(
            shipment_id, ShipmentStatus.DELIVERED, mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentDelivered(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    delivered_at=s.delivered_at.isoformat() if s.delivered_at else None,
                    previous_status=prev.value,
                )
            ],
        )

    def fail_shipment(self, shipment_id, *, reason: Optional[str] = None) -> Shipment:
        """in_transit/delayed → failed."""
        def _mutate(s: Shipment) -> None:
            s.failed_at = utcnow()
            s.failure_reason = reason

        return self._transition(
            shipment_id, ShipmentStatus.FAILED, reason=reason, mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentFailed(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    previous_status=prev.value, reason=reason,
                )
            ],
        )

    def return_shipment(self, shipment_id, *, reason: Optional[str] = None) -> Shipment:
        """in_transit/delayed/failed → returned (terminal)."""
        def _mutate(s: Shipment) -> None:
            s.return_reason = reason

        return self._transition(
            shipment_id, ShipmentStatus.RETURNED, reason=reason, mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentReturned(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    previous_status=prev.value, reason=reason,
                )
            ],
        )

    def cancel_shipment(self, shipment_id, *, reason: Optional[str] = None) -> Shipment:
        """any pre-delivered state → cancelled (terminal); flags compensation."""
        def _mutate(s: Shipment) -> None:
            s.cancelled_at = utcnow()

        def _cancelled(s: Shipment, prev: ShipmentStatus) -> object:
            return ShipmentCancelled(
                shipment_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value,
                reason=reason, compensation_required=ShipmentStateMachine.requires_compensation(prev),
            )

        return self._transition(
            shipment_id, ShipmentStatus.CANCELLED, reason=reason, mutate=_mutate,
            extra_events=[_cancelled],
        )

    # ------------------------------------------------------------------
    # Legacy entry points (backward compatibility)
    # ------------------------------------------------------------------

    def assign_driver_and_vehicle(self, shipment_id: str, driver_id: str, vehicle_id: str) -> Shipment:
        """Legacy alias for :meth:`assign_shipment` (driver + vehicle)."""
        return self.assign_shipment(shipment_id, driver_id=driver_id, vehicle_id=vehicle_id)

    def assign_driver_only(self, shipment_id: str, driver_id: str) -> Shipment:
        """Driver self-accept (mobile): ready/created → assigned, driver only."""
        tenant_id = self._tenant_id()
        shipment = self._shipments.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found (deleted).")
        if shipment.status not in {ShipmentStatus.READY, ShipmentStatus.CREATED}:
            raise AssignmentError("Shipment is not open for acceptance.")

        driver = self._require_driver(driver_id, tenant_id)
        self._validate_driver(driver)
        self._assert_driver_not_busy(driver.id, exclude=shipment.id)

        prev_driver = shipment.driver_id

        def _mutate(s: Shipment) -> None:
            s.driver_id = driver.id
            s.assigned_at = utcnow()

        # Allow CREATED→ASSIGNED for the self-accept path (offer claim).
        if shipment.status == ShipmentStatus.CREATED:
            shipment.status = ShipmentStatus.READY  # normalize to a valid pre-assign state

        return self._transition(
            shipment_id, ShipmentStatus.ASSIGNED, mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentAssigned(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    driver_id=s.driver_id, vehicle_id=s.vehicle_id, previous_status=prev.value,
                ),
                lambda s, prev: ShipmentDriverChanged(
                    shipment_id=s.id, tenant_id=s.tenant_id,
                    previous_driver_id=prev_driver, new_driver_id=s.driver_id,
                ),
            ],
        )

    # Map of the legacy generic status transition to the specific operations.
    _LEGACY_TRANSITIONS: Dict[ShipmentStatus, str] = {
        ShipmentStatus.READY: "mark_ready",
        ShipmentStatus.PICKED_UP: "pickup_shipment",
        ShipmentStatus.IN_TRANSIT: "start_transit",
        ShipmentStatus.DELAYED: "mark_delayed",
        ShipmentStatus.DELIVERED: "deliver_shipment",
        ShipmentStatus.FAILED: "fail_shipment",
        ShipmentStatus.RETURNED: "return_shipment",
        ShipmentStatus.CANCELLED: "cancel_shipment",
    }

    def transition_status(self, shipment_id: str, new_status: ShipmentStatus) -> Shipment:
        """Legacy generic transition — routes to the specific lifecycle op."""
        op_name = self._LEGACY_TRANSITIONS.get(new_status)
        if op_name is None:
            raise StatusTransitionError(f"Unsupported target status '{new_status.value}'.")
        return getattr(self, op_name)(shipment_id)

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
        """Append a tracking event and optionally advance status (emits events)."""
        tenant_id = self._tenant_id()
        shipment = self._shipments.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found (deleted).")

        last_event_time = self._get_latest_event_time(shipment.id)
        if last_event_time and event_time < last_event_time:
            raise TrackingEventError("event_time must be equal or later than the last recorded event.")

        previous = shipment.status
        if status is not None and status != previous:
            ShipmentStateMachine.validate_transition(previous, status)

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

        if status is not None and status != previous:
            shipment.status = status
            if status == ShipmentStatus.DELIVERED:
                shipment.delivered_at = event_time
            elif status == ShipmentStatus.CANCELLED:
                shipment.cancelled_at = event_time
            elif status == ShipmentStatus.PICKED_UP:
                shipment.picked_up_at = event_time
            elif status == ShipmentStatus.FAILED:
                shipment.failed_at = event_time
            self._session.flush()
            self._emit(
                ShipmentStatusChanged(
                    shipment_id=shipment.id, tenant_id=tenant_id,
                    previous_status=previous.value, new_status=status.value, reason=notes,
                ),
                aggregate_id=shipment.id, tenant_id=tenant_id,
            )

        self._session.commit()
        self._session.refresh(event)
        return event

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _assert_user_in_tenant(self, user_id, tenant_id, *, label: str) -> None:
        user = self._users.get_by_id(user_id) if user_id else None
        if user is None or getattr(user, "tenant_id", None) != tenant_id:
            raise ValidationError(f"{label} {user_id} does not exist in this tenant.")

    def _assert_order_in_tenant(self, order_id, tenant_id) -> None:
        order = self._orders.get_by_id(order_id)
        if order is None or order.is_deleted or order.tenant_id != tenant_id:
            raise ValidationError(f"Order {order_id} does not exist in this tenant.")

    def _assert_warehouse_in_tenant(self, warehouse_id, tenant_id) -> None:
        wh = self._warehouses.get_by_id(warehouse_id)
        if wh is None or getattr(wh, "tenant_id", None) != tenant_id:
            raise ValidationError(f"Warehouse {warehouse_id} does not exist in this tenant.")

    def _require_driver(self, driver_id, tenant_id) -> Driver:
        driver = self._drivers.get_by_id(driver_id)
        if driver is None:
            raise NotFoundError("Driver not found.")
        if getattr(driver, "tenant_id", None) != tenant_id:
            raise ValidationError("Driver does not belong to this tenant.")
        return driver

    def _require_vehicle(self, vehicle_id, tenant_id) -> Vehicle:
        vehicle = self._vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle not found.")
        if getattr(vehicle, "tenant_id", None) != tenant_id:
            raise ValidationError("Vehicle does not belong to this tenant.")
        return vehicle

    def _assert_warehouses_exist(self, origin_id, destination_id) -> None:
        tenant_id = self._tenant_id()
        self._assert_warehouse_in_tenant(origin_id, tenant_id)
        self._assert_warehouse_in_tenant(destination_id, tenant_id)

    def _assert_capacity(self, warehouse_id, added_weight: float, added_volume: float) -> None:
        warehouse = self._warehouses.get_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError("Warehouse not found.")
        current_weight, current_volume = self._current_load_for_warehouse(warehouse_id)
        if current_weight + added_weight > float(warehouse.capacity_weight_kg):
            raise CapacityError("Warehouse weight capacity would be exceeded.")
        if current_volume + added_volume > float(warehouse.capacity_volume_m3):
            raise CapacityError("Warehouse volume capacity would be exceeded.")

    def _current_load_for_warehouse(self, warehouse_id) -> tuple[float, float]:
        active = tuple(ACTIVE_STATUSES)
        stmt = select(
            func.coalesce(func.sum(Shipment.weight_kg), 0),
            func.coalesce(func.sum(Shipment.volume_m3), 0),
        ).where(
            or_(
                Shipment.origin_warehouse_id == warehouse_id,
                Shipment.destination_warehouse_id == warehouse_id,
            ),
            Shipment.status.in_(active),
            Shipment.deleted_at.is_(None),
        )
        weight, volume = self._session.execute(stmt).one()
        return float(weight), float(volume)

    def _validate_driver(self, driver: Driver) -> None:
        if driver.user is None or driver.user.role != UserRole.DRIVER:
            raise AssignmentError("Driver profile is not linked to a driver-role user.")
        if not driver.is_available:
            raise AssignmentError("Driver is marked unavailable for assignments.")

    def _validate_vehicle(self, vehicle: Vehicle) -> None:
        if vehicle.status != VehicleStatus.ACTIVE:
            raise AssignmentError("Vehicle is not active for assignments.")

    def _assert_driver_not_busy(self, driver_id, exclude) -> None:
        if self._shipments.count_active_for_driver(driver_id, exclude_shipment_id=exclude) > 0:
            raise AssignmentError("Driver already assigned to an active shipment.")

    def _assert_vehicle_not_busy(self, vehicle_id, exclude) -> None:
        if self._shipments.count_active_for_vehicle(vehicle_id, exclude_shipment_id=exclude) > 0:
            raise AssignmentError("Vehicle already assigned to an active shipment.")

    def _assert_vehicle_capacity(self, vehicle: Vehicle, shipment: Shipment) -> None:
        if float(shipment.weight_kg) > float(vehicle.capacity_weight_kg):
            raise AssignmentError("Shipment exceeds vehicle weight capacity.")
        if float(shipment.volume_m3) > float(vehicle.capacity_volume_m3):
            raise AssignmentError("Shipment exceeds vehicle volume capacity.")

    def _get_latest_event_time(self, shipment_id) -> Optional[datetime]:
        stmt = (
            select(ShipmentTrackingEvent.event_time)
            .where(ShipmentTrackingEvent.shipment_id == shipment_id)
            .order_by(ShipmentTrackingEvent.event_time.desc())
            .limit(1)
        )
        result = self._session.execute(stmt).first()
        return result[0] if result else None


def _jsonable(data: Dict[str, object]) -> Dict[str, object]:
    """Coerce update values into JSON-safe primitives for event payloads."""
    from app.events.domain_event import to_jsonable

    return {k: to_jsonable(v) for k, v in data.items()}
