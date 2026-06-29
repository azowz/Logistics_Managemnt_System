"""Shipment service — application layer for the Shipment aggregate (Sprint 5).

Responsibilities:
  * Enforce business rules (tenant ownership of related aggregates, reference
    uniqueness, the lifecycle state machine, assignment eligibility/exclusivity,
    capacity, soft-delete).
  * Own the unit of work (a single ``session.commit()`` per operation).
  * Emit domain events into the transactional outbox in the same transaction.
  * Never import FastAPI/HTTP types — failures are domain exceptions.

State-changing operations follow the Sprint 3/4 pattern::

    validate tenant context → load aggregate → validate business rules →
    mutate aggregate → session.flush() → create Domain Event →
    EventEnvelope.create() → EventStoreRepository.append() → session.commit()

Legacy methods (``assign_driver_only``, ``assign_driver_and_vehicle``,
``transition_status``, ``create_tracking_event``) are preserved for the mobile
driver flow and the tracking-event ingestion route; they now route status
changes through :class:`~app.services.shipment_policies.ShipmentStateMachine`
and emit events like the new lifecycle methods.
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
from app.models.enums import (
    ShipmentStatus,
    TrackingEventType,
    UserRole,
    VehicleStatus,
)
from app.models.shipment import Shipment
from app.models.shipment_tracking_event import ShipmentTrackingEvent
from app.models.enums import EquipmentStatus
from app.repositories.driver_repository import DriverRepository
from app.repositories.equipment_repository import EquipmentRepository
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
from app.services.equipment_policies import EquipmentStateMachine
from app.services.shipment_policies import ShipmentStateMachine

_AGGREGATE_TYPE = "Shipment"

# Statuses that reserve warehouse capacity / count as in-flight.
ACTIVE_STATUSES = {
    ShipmentStatus.CREATED,
    ShipmentStatus.READY,
    ShipmentStatus.ASSIGNED,
    ShipmentStatus.PICKED_UP,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.DELAYED,
}

# Field → fine-grained event partitioning for update_shipment.
_ADDRESS_FIELDS = frozenset({"origin_warehouse_id", "destination_warehouse_id"})
_CARGO_FIELDS = frozenset(
    {"cargo_type", "cargo_description", "weight_kg", "volume_m3"}
)


class ShipmentService:
    """Orchestrates Shipment persistence, validation, and event emission."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ShipmentRepository(session)
        self._orders = OrderRepository(session)
        self._users = UserRepository(session)
        self._drivers = DriverRepository(session)
        self._vehicles = VehicleRepository(session)
        self._warehouses = WarehouseRepository(session)
        self._equipment = EquipmentRepository(session)
        self._tracking_events = TrackingEventRepository(session)
        self._event_repo = EventStoreRepository(session)

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError(
                "No tenant context found; request is not authenticated."
            )
        return tid

    def _actor_id(self) -> Optional[uuid.UUID]:
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Wrap a domain event and append it to the transactional outbox."""
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

    @staticmethod
    def _generate_reference_code() -> str:
        """Generate a tenant-unique-ish reference; uniqueness is re-checked."""
        return f"SHP-{uuid.uuid4().hex[:12].upper()}"

    # ------------------------------------------------------------------
    # Tenant-ownership validation of related aggregates
    # ------------------------------------------------------------------

    def _require_tenant_owned(
        self, obj, tenant_id: uuid.UUID, label: str, identifier
    ):
        """Validate ``obj`` exists, is not soft-deleted, and belongs to tenant."""
        if (
            obj is None
            or getattr(obj, "is_deleted", False)
            or getattr(obj, "tenant_id", None) != tenant_id
        ):
            raise ValidationError(
                f"{label} {identifier} does not exist in this tenant."
            )
        return obj

    def _validate_related(
        self,
        *,
        tenant_id: uuid.UUID,
        client_id: uuid.UUID,
        origin_warehouse_id: uuid.UUID,
        destination_warehouse_id: uuid.UUID,
        order_id: Optional[uuid.UUID],
        equipment_id: Optional[uuid.UUID],
    ) -> None:
        """Validate all create-time FK references belong to the current tenant."""
        self._require_tenant_owned(
            self._users.get_by_id(client_id), tenant_id, "Client", client_id
        )
        self._require_tenant_owned(
            self._warehouses.get_by_id(origin_warehouse_id),
            tenant_id,
            "Origin warehouse",
            origin_warehouse_id,
        )
        self._require_tenant_owned(
            self._warehouses.get_by_id(destination_warehouse_id),
            tenant_id,
            "Destination warehouse",
            destination_warehouse_id,
        )
        if order_id is not None:
            self._require_tenant_owned(
                self._orders.get_by_id(order_id), tenant_id, "Order", order_id
            )
        # equipment_id is validated separately (needs shipment weight/volume and
        # the exclude-self id) via :meth:`_validate_equipment` (Sprint 6).

    def _validate_equipment(
        self,
        *,
        tenant_id: uuid.UUID,
        equipment_id: uuid.UUID,
        weight_kg,
        volume_m3,
        exclude_shipment_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Validate a referenced equipment unit (Sprint 6 integration, ADR-009).

        The equipment must exist in the tenant, not be decommissioned, be in an
        assignable state, not already be bound to another active shipment, and be
        dimensionally compatible with the shipment's declared weight/volume.
        """
        equipment = self._require_tenant_owned(
            self._equipment.get_by_id(equipment_id),
            tenant_id,
            "Equipment",
            equipment_id,
        )
        if equipment.status == EquipmentStatus.DECOMMISSIONED:
            raise ValidationError(
                f"Equipment {equipment_id} is decommissioned and cannot be shipped."
            )
        if not EquipmentStateMachine.is_assignable(equipment.status):
            raise ConflictError(
                f"Equipment {equipment_id} is in status '{equipment.status.value}' "
                "and cannot be assigned to a shipment."
            )
        if self._repo.has_active_equipment_assignment(
            equipment_id, exclude_shipment_id=exclude_shipment_id
        ):
            raise ConflictError(
                f"Equipment {equipment_id} is already assigned to an active shipment."
            )
        # Dimensional compatibility: the shipment's declared weight/volume must at
        # least cover the equipment unit it carries (when both are known).
        if equipment.weight_kg is not None and weight_kg is not None:
            if float(weight_kg) < float(equipment.weight_kg):
                raise ValidationError(
                    "Shipment weight is below the equipment's weight; incompatible load."
                )
        if equipment.volume_m3 is not None and volume_m3 is not None:
            if float(volume_m3) < float(equipment.volume_m3):
                raise ValidationError(
                    "Shipment volume is below the equipment's volume; incompatible load."
                )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_shipment(
        self,
        *,
        reference_code: Optional[str] = None,
        **data,
    ) -> Shipment:
        """Create and persist a new shipment in ``created`` status.

        Raises:
            :exc:`ValidationError`: When a related aggregate is missing or
                belongs to another tenant.
            :exc:`ConflictError`: When ``reference_code`` already exists.
            :exc:`CapacityError`: When warehouse capacity would be exceeded.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        client_id = data["client_id"]
        origin_warehouse_id = data["origin_warehouse_id"]
        destination_warehouse_id = data["destination_warehouse_id"]
        order_id = data.get("order_id")
        equipment_id = data.get("equipment_id")

        self._validate_related(
            tenant_id=tenant_id,
            client_id=client_id,
            origin_warehouse_id=origin_warehouse_id,
            destination_warehouse_id=destination_warehouse_id,
            order_id=order_id,
            equipment_id=equipment_id,
        )
        if equipment_id is not None:
            self._validate_equipment(
                tenant_id=tenant_id,
                equipment_id=equipment_id,
                weight_kg=data.get("weight_kg"),
                volume_m3=data.get("volume_m3"),
            )

        reference = reference_code or self._generate_reference_code()
        if self._repo.get_by_reference_code(reference):
            raise ConflictError(
                f"Shipment reference '{reference}' already exists in this tenant."
            )

        # Warehouse capacity guard (preserved from the legacy service).
        self._assert_capacity(
            origin_warehouse_id,
            float(data["weight_kg"]),
            float(data["volume_m3"]),
        )
        self._assert_capacity(
            destination_warehouse_id,
            float(data["weight_kg"]),
            float(data["volume_m3"]),
        )

        # Status is always CREATED on creation regardless of input.
        data.pop("status", None)

        shipment = self._repo.create(
            tenant_id=tenant_id,
            reference_code=reference,
            status=ShipmentStatus.CREATED,
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()  # assigns shipment.id

        self._emit(
            ShipmentCreated(
                shipment_id=shipment.id,
                tenant_id=tenant_id,
                reference_code=shipment.reference_code,
                client_id=shipment.client_id,
                origin_warehouse_id=shipment.origin_warehouse_id,
                destination_warehouse_id=shipment.destination_warehouse_id,
                order_id=shipment.order_id,
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

    def get_shipment(
        self, shipment_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Shipment:
        """Return a shipment by ID, raising :exc:`NotFoundError` if absent/deleted."""
        shipment = self._repo.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        if shipment.is_deleted and not include_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        return shipment

    def list_shipments(self, params: ShipmentListParams) -> Page[Shipment]:
        """Return a paginated, filtered, sorted list of shipments."""
        items, total = self._repo.list_shipments(
            q=params.q,
            status=params.status,
            priority=params.priority,
            driver_id=params.driver_id,
            vehicle_id=params.vehicle_id,
            order_id=params.order_id,
            client_id=params.client_id,
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

    # search_shipments is an alias for list_shipments (q-driven free-text search).
    search_shipments = list_shipments

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_shipment(self, shipment_id: uuid.UUID, **data) -> Shipment:
        """Apply partial updates to a shipment (PATCH semantics).

        Emits :class:`ShipmentAddressChanged` for warehouse changes,
        :class:`ShipmentCargoChanged` for cargo changes, and a general
        :class:`ShipmentUpdated` for the remainder.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._repo.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found (deleted).")
        if ShipmentStateMachine.is_terminal(shipment.status):
            raise ValidationError(
                f"Shipment {shipment_id} is in terminal state "
                f"'{shipment.status.value}' and cannot be edited."
            )

        applied = {k: v for k, v in data.items() if v is not None}

        # Validate any changed warehouse references belong to the tenant.
        if "origin_warehouse_id" in applied:
            self._require_tenant_owned(
                self._warehouses.get_by_id(applied["origin_warehouse_id"]),
                tenant_id,
                "Origin warehouse",
                applied["origin_warehouse_id"],
            )
        if "destination_warehouse_id" in applied:
            self._require_tenant_owned(
                self._warehouses.get_by_id(applied["destination_warehouse_id"]),
                tenant_id,
                "Destination warehouse",
                applied["destination_warehouse_id"],
            )
        if applied.get("order_id") is not None:
            self._require_tenant_owned(
                self._orders.get_by_id(applied["order_id"]),
                tenant_id,
                "Order",
                applied["order_id"],
            )
        if applied.get("equipment_id") is not None:
            self._validate_equipment(
                tenant_id=tenant_id,
                equipment_id=applied["equipment_id"],
                weight_kg=applied.get("weight_kg", shipment.weight_kg),
                volume_m3=applied.get("volume_m3", shipment.volume_m3),
                exclude_shipment_id=shipment.id,
            )

        # Reference-code uniqueness (when changed).
        if "reference_code" in applied and applied["reference_code"] != shipment.reference_code:
            existing = self._repo.get_by_reference_code(applied["reference_code"])
            if existing is not None and existing.id != shipment.id:
                raise ConflictError(
                    f"Shipment reference '{applied['reference_code']}' already exists."
                )

        address_changes = {k: v for k, v in applied.items() if k in _ADDRESS_FIELDS}
        cargo_changes = {k: v for k, v in applied.items() if k in _CARGO_FIELDS}
        other_changes = {
            k: v
            for k, v in applied.items()
            if k not in _ADDRESS_FIELDS and k not in _CARGO_FIELDS
        }

        data["updated_by"] = actor_id
        self._repo.update(shipment, **data)
        self._session.flush()

        if address_changes:
            self._emit(
                ShipmentAddressChanged(
                    shipment_id=shipment.id,
                    tenant_id=tenant_id,
                    changed_fields=_jsonable(address_changes),
                ),
                aggregate_id=shipment.id,
                tenant_id=tenant_id,
            )
        if cargo_changes:
            self._emit(
                ShipmentCargoChanged(
                    shipment_id=shipment.id,
                    tenant_id=tenant_id,
                    changed_fields=_jsonable(cargo_changes),
                ),
                aggregate_id=shipment.id,
                tenant_id=tenant_id,
            )
        if other_changes:
            self._emit(
                ShipmentUpdated(
                    shipment_id=shipment.id,
                    tenant_id=tenant_id,
                    changed_fields=_jsonable(other_changes),
                ),
                aggregate_id=shipment.id,
                tenant_id=tenant_id,
            )

        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    # ------------------------------------------------------------------
    # Generic validated transition
    # ------------------------------------------------------------------

    def _transition(
        self,
        shipment_id: uuid.UUID,
        new_status: ShipmentStatus,
        *,
        reason: Optional[str] = None,
        mutate: Optional[Callable[[Shipment], None]] = None,
        extra_events: Optional[
            List[Callable[[Shipment, ShipmentStatus], object]]
        ] = None,
    ) -> Shipment:
        """Validated status transition + event emission in one transaction."""
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._repo.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found (deleted).")

        previous = shipment.status
        if new_status == previous:
            return shipment  # idempotent no-op

        ShipmentStateMachine.validate_transition(previous, new_status)

        if mutate is not None:
            mutate(shipment)
        shipment.status = new_status
        shipment.updated_by = actor_id
        self._session.flush()

        for factory in extra_events or []:
            self._emit(
                factory(shipment, previous),
                aggregate_id=shipment.id,
                tenant_id=tenant_id,
            )

        self._emit(
            ShipmentStatusChanged(
                shipment_id=shipment.id,
                tenant_id=tenant_id,
                previous_status=previous.value,
                new_status=new_status.value,
                reason=reason,
            ),
            aggregate_id=shipment.id,
            tenant_id=tenant_id,
        )

        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def mark_ready(self, shipment_id: uuid.UUID) -> Shipment:
        """created → ready."""
        return self._transition(
            shipment_id,
            ShipmentStatus.READY,
            extra_events=[
                lambda s, prev: ShipmentMarkedReady(
                    shipment_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value
                )
            ],
        )

    def assign_shipment(
        self,
        shipment_id: uuid.UUID,
        *,
        driver_id: uuid.UUID,
        vehicle_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> Shipment:
        """ready → assigned. Requires an available driver and vehicle (tenant-owned).

        Validates eligibility, exclusivity, and vehicle capacity before binding
        the driver/vehicle to the shipment.
        """
        tenant_id = self._tenant_id()
        shipment = self._repo.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} not found (deleted).")

        driver = self._require_tenant_owned(
            self._drivers.get_by_id(driver_id), tenant_id, "Driver", driver_id
        )
        vehicle = self._require_tenant_owned(
            self._vehicles.get_by_id(vehicle_id), tenant_id, "Vehicle", vehicle_id
        )

        self._validate_driver(driver)
        self._validate_vehicle(vehicle)
        if self._repo.has_active_driver_assignment(
            driver.id, exclude_shipment_id=shipment.id
        ):
            raise AssignmentError("Driver already assigned to an active shipment.")
        if self._repo.has_active_vehicle_assignment(
            vehicle.id, exclude_shipment_id=shipment.id
        ):
            raise AssignmentError("Vehicle already assigned to an active shipment.")
        self._assert_vehicle_capacity(vehicle, shipment)

        def _mutate(s: Shipment) -> None:
            s.driver_id = driver.id
            s.vehicle_id = vehicle.id
            s.assigned_at = utcnow()

        return self._transition(
            shipment_id,
            ShipmentStatus.ASSIGNED,
            reason=reason,
            mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentAssigned(
                    shipment_id=s.id,
                    tenant_id=s.tenant_id,
                    driver_id=s.driver_id,
                    vehicle_id=s.vehicle_id,
                    previous_status=prev.value,
                )
            ],
        )

    def pickup_shipment(self, shipment_id: uuid.UUID) -> Shipment:
        """assigned → picked_up."""
        def _mutate(s: Shipment) -> None:
            s.picked_up_at = utcnow()

        return self._transition(
            shipment_id,
            ShipmentStatus.PICKED_UP,
            mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentPickedUp(
                    shipment_id=s.id,
                    tenant_id=s.tenant_id,
                    picked_up_at=s.picked_up_at.isoformat() if s.picked_up_at else None,
                    previous_status=prev.value,
                )
            ],
        )

    def start_transit(self, shipment_id: uuid.UUID) -> Shipment:
        """picked_up → in_transit (also resumes delayed → in_transit)."""
        return self._transition(
            shipment_id,
            ShipmentStatus.IN_TRANSIT,
            extra_events=[
                lambda s, prev: ShipmentInTransit(
                    shipment_id=s.id, tenant_id=s.tenant_id, previous_status=prev.value
                )
            ],
        )

    def mark_delayed(
        self, shipment_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Shipment:
        """in_transit → delayed (overlay; resumeable via start_transit)."""
        return self._transition(
            shipment_id,
            ShipmentStatus.DELAYED,
            reason=reason,
            extra_events=[
                lambda s, prev: ShipmentDelayed(
                    shipment_id=s.id,
                    tenant_id=s.tenant_id,
                    previous_status=prev.value,
                    reason=reason,
                )
            ],
        )

    def deliver_shipment(self, shipment_id: uuid.UUID) -> Shipment:
        """in_transit/delayed → delivered (terminal)."""
        def _mutate(s: Shipment) -> None:
            s.delivered_at = utcnow()

        return self._transition(
            shipment_id,
            ShipmentStatus.DELIVERED,
            extra_events=[
                lambda s, prev: ShipmentDelivered(
                    shipment_id=s.id,
                    tenant_id=s.tenant_id,
                    delivered_at=s.delivered_at.isoformat() if s.delivered_at else None,
                    previous_status=prev.value,
                )
            ],
        )

    def fail_shipment(
        self, shipment_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Shipment:
        """in-progress → failed."""
        def _mutate(s: Shipment) -> None:
            s.failed_at = utcnow()
            s.failure_reason = reason

        return self._transition(
            shipment_id,
            ShipmentStatus.FAILED,
            reason=reason,
            mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentFailed(
                    shipment_id=s.id,
                    tenant_id=s.tenant_id,
                    previous_status=prev.value,
                    reason=reason,
                )
            ],
        )

    def return_shipment(
        self, shipment_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Shipment:
        """in_transit/delayed/failed → returned (terminal)."""
        def _mutate(s: Shipment) -> None:
            s.return_reason = reason

        return self._transition(
            shipment_id,
            ShipmentStatus.RETURNED,
            reason=reason,
            mutate=_mutate,
            extra_events=[
                lambda s, prev: ShipmentReturned(
                    shipment_id=s.id,
                    tenant_id=s.tenant_id,
                    previous_status=prev.value,
                    reason=reason,
                )
            ],
        )

    def cancel_shipment(
        self, shipment_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Shipment:
        """any pre-delivery → cancelled (terminal). Flags compensation when needed."""
        def _mutate(s: Shipment) -> None:
            s.cancelled_at = utcnow()

        def _cancelled_event(s: Shipment, prev: ShipmentStatus) -> object:
            return ShipmentCancelled(
                shipment_id=s.id,
                tenant_id=s.tenant_id,
                previous_status=prev.value,
                reason=reason,
                compensation_required=ShipmentStateMachine.requires_compensation(prev),
            )

        return self._transition(
            shipment_id,
            ShipmentStatus.CANCELLED,
            reason=reason,
            mutate=_mutate,
            extra_events=[_cancelled_event],
        )

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def delete_shipment(self, shipment_id: uuid.UUID) -> None:
        """Soft-delete a shipment."""
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._repo.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError(f"Shipment {shipment_id} is already deleted.")

        self._repo.soft_delete(shipment, deleted_by=actor_id)
        shipment.updated_by = actor_id
        self._session.flush()

        self._emit(
            ShipmentDeleted(
                shipment_id=shipment.id, tenant_id=tenant_id, deleted_by=actor_id
            ),
            aggregate_id=shipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()

    def restore_shipment(self, shipment_id: uuid.UUID) -> Shipment:
        """Restore a soft-deleted shipment."""
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._repo.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        if not shipment.is_deleted:
            raise ValidationError(
                f"Shipment {shipment_id} is not deleted; nothing to restore."
            )

        self._repo.restore(shipment)
        shipment.updated_by = actor_id
        self._session.flush()

        self._emit(
            ShipmentRestored(shipment_id=shipment.id, tenant_id=tenant_id),
            aggregate_id=shipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    # ==================================================================
    # Legacy API (preserved for the mobile driver flow + tracking route)
    # ==================================================================

    def assign_driver_and_vehicle(
        self, shipment_id: str, driver_id: str, vehicle_id: str
    ) -> Shipment:
        """Legacy: full driver+vehicle assignment. Delegates to assign_shipment."""
        return self.assign_shipment(
            uuid.UUID(str(shipment_id)),
            driver_id=uuid.UUID(str(driver_id)),
            vehicle_id=uuid.UUID(str(vehicle_id)),
        )

    def assign_driver_only(self, shipment_id: str, driver_id: str) -> Shipment:
        """Legacy self-accept flow: assign just a driver (vehicle bound later).

        Reuses the eligibility + exclusivity guards but does not bind a vehicle.
        The shipment must be in a pre-transit (created/ready) state. Emits
        :class:`ShipmentAssigned` (with ``vehicle_id=None``).
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        shipment = self._repo.get_by_id_or_raise(shipment_id)
        if shipment.is_deleted:
            raise NotFoundError("Shipment not found.")

        driver = self._drivers.get_by_id(driver_id)
        if driver is None:
            raise NotFoundError("Driver not found.")
        self._validate_driver(driver)
        if self._repo.has_active_driver_assignment(
            driver.id, exclude_shipment_id=shipment.id
        ):
            raise AssignmentError("Driver already assigned to an active shipment.")

        if shipment.status not in {ShipmentStatus.READY, ShipmentStatus.CREATED}:
            raise AssignmentError("Shipment is not open for acceptance.")

        previous = shipment.status
        shipment.driver_id = driver.id
        shipment.assigned_at = utcnow()
        shipment.status = ShipmentStatus.ASSIGNED
        shipment.updated_by = actor_id
        self._session.flush()

        self._emit(
            ShipmentAssigned(
                shipment_id=shipment.id,
                tenant_id=shipment.tenant_id,
                driver_id=shipment.driver_id,
                vehicle_id=None,
                previous_status=previous.value,
            ),
            aggregate_id=shipment.id,
            tenant_id=tenant_id,
        )
        self._emit(
            ShipmentStatusChanged(
                shipment_id=shipment.id,
                tenant_id=tenant_id,
                previous_status=previous.value,
                new_status=ShipmentStatus.ASSIGNED.value,
                reason="driver self-accept",
            ),
            aggregate_id=shipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    def transition_status(
        self, shipment_id: str, new_status: ShipmentStatus
    ) -> Shipment:
        """Legacy generic status transition routed through the state machine."""
        def _mutate(s: Shipment) -> None:
            now = utcnow()
            if new_status == ShipmentStatus.CANCELLED:
                s.cancelled_at = now
            elif new_status == ShipmentStatus.DELIVERED:
                s.delivered_at = now
            elif new_status == ShipmentStatus.ASSIGNED:
                s.assigned_at = now
            elif new_status == ShipmentStatus.PICKED_UP:
                s.picked_up_at = now
            elif new_status == ShipmentStatus.FAILED:
                s.failed_at = now

        return self._transition(
            uuid.UUID(str(shipment_id)), new_status, mutate=_mutate
        )

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
        """Append a tracking event and optionally advance shipment status.

        The append-only tracking history is independent of the event store; when
        a status change is requested it is validated against
        :class:`ShipmentStateMachine` and emits a :class:`ShipmentStatusChanged`.
        """
        tenant_id = self._tenant_id()
        shipment = self._repo.get_by_id_or_raise(shipment_id)

        last_event_time = self._get_latest_event_time(shipment.id)
        if last_event_time and event_time < last_event_time:
            raise TrackingEventError(
                "event_time must be equal or later than the last recorded event."
            )

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
            self._session.flush()
            self._emit(
                ShipmentStatusChanged(
                    shipment_id=shipment.id,
                    tenant_id=tenant_id,
                    previous_status=previous.value,
                    new_status=status.value,
                    reason="tracking event",
                ),
                aggregate_id=shipment.id,
                tenant_id=tenant_id,
            )

        self._session.commit()
        self._session.refresh(event)
        return event

    # ------------------------------------------------------------------
    # Internal eligibility / capacity helpers
    # ------------------------------------------------------------------

    def _validate_driver(self, driver) -> None:
        """Ensure a driver is eligible for assignment."""
        if driver.user is None or driver.user.role != UserRole.DRIVER:
            raise AssignmentError(
                "Driver profile is not linked to a driver-role user."
            )
        if not driver.is_available:
            raise AssignmentError("Driver is marked unavailable for assignments.")

    def _validate_vehicle(self, vehicle) -> None:
        """Ensure a vehicle is eligible for assignment."""
        if vehicle.status != VehicleStatus.ACTIVE:
            raise AssignmentError("Vehicle is not active for assignments.")

    def _assert_vehicle_capacity(self, vehicle, shipment: Shipment) -> None:
        """Ensure the vehicle can carry the shipment's load."""
        if float(shipment.weight_kg) > float(vehicle.capacity_weight_kg):
            raise AssignmentError("Shipment exceeds vehicle weight capacity.")
        if float(shipment.volume_m3) > float(vehicle.capacity_volume_m3):
            raise AssignmentError("Shipment exceeds vehicle volume capacity.")

    def _assert_capacity(
        self, warehouse_id, added_weight: float, added_volume: float
    ) -> None:
        """Ensure adding a shipment will not exceed warehouse capacity."""
        warehouse = self._warehouses.get_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError("Warehouse not found.")

        current_weight, current_volume = self._current_load_for_warehouse(warehouse_id)
        if current_weight + added_weight > float(warehouse.capacity_weight_kg):
            raise CapacityError("Warehouse weight capacity would be exceeded.")
        if current_volume + added_volume > float(warehouse.capacity_volume_m3):
            raise CapacityError("Warehouse volume capacity would be exceeded.")

    def _current_load_for_warehouse(self, warehouse_id) -> tuple[float, float]:
        """Active weight and volume reserved against a warehouse."""
        weight_sum = func.coalesce(func.sum(Shipment.weight_kg), 0)
        volume_sum = func.coalesce(func.sum(Shipment.volume_m3), 0)
        statement = select(weight_sum, volume_sum).where(
            or_(
                Shipment.origin_warehouse_id == warehouse_id,
                Shipment.destination_warehouse_id == warehouse_id,
            ),
            Shipment.status.in_(tuple(ACTIVE_STATUSES)),
            Shipment.deleted_at.is_(None),
        )
        weight, volume = self._session.execute(statement).one()
        return float(weight), float(volume)

    def _get_latest_event_time(self, shipment_id) -> Optional[datetime]:
        """Most recent tracking-event time, to enforce monotonic ordering."""
        statement = (
            select(ShipmentTrackingEvent.event_time)
            .where(ShipmentTrackingEvent.shipment_id == shipment_id)
            .order_by(ShipmentTrackingEvent.event_time.desc())
            .limit(1)
        )
        result = self._session.execute(statement).first()
        return result[0] if result else None


def _jsonable(data: Dict[str, object]) -> Dict[str, object]:
    """Coerce update values into JSON-safe primitives for event payloads."""
    from app.events.domain_event import to_jsonable

    return {k: to_jsonable(v) for k, v in data.items()}
