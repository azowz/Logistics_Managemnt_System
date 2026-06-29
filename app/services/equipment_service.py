"""Equipment service — application layer for the Equipment aggregate (Sprint 6).

Owns the unit of work and the transactional outbox emission for the Equipment &
Asset context (#15). Mirrors the Customer/Order/Shipment services:

    validate tenant context → load aggregate → validate business rules →
    mutate aggregate → session.flush() → DomainEvent → EventEnvelope.create() →
    EventStoreRepository.append() → session.commit()

No FastAPI imports; failures are domain exceptions. Cross-context references
(category, model, warehouse, shipment) are validated tenant-owned via read-only
repositories — no circular service dependency.
"""

from __future__ import annotations

import uuid
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.equipment_events import (
    EquipmentActivated,
    EquipmentAssignedToShipment,
    EquipmentCreated,
    EquipmentDeactivated,
    EquipmentDecommissioned,
    EquipmentDelivered,
    EquipmentDeleted,
    EquipmentInTransit,
    EquipmentLocationChanged,
    EquipmentMaintenanceCompleted,
    EquipmentMaintenanceStarted,
    EquipmentReleased,
    EquipmentReserved,
    EquipmentRestored,
    EquipmentSpecificationChanged,
    EquipmentStatusChanged,
    EquipmentUpdated,
)
from app.models.enums import EquipmentAvailability, EquipmentStatus
from app.models.equipment import Equipment
from app.repositories.equipment_repository import (
    EquipmentCategoryRepository,
    EquipmentModelRepository,
    EquipmentRepository,
)
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.shipment_repository import ShipmentRepository
from app.repositories.warehouse_repository import WarehouseRepository
from app.schemas.equipment import EquipmentListParams
from app.services.equipment_policies import EquipmentStateMachine
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

_AGGREGATE_TYPE = "Equipment"

_LOCATION_FIELDS = frozenset({"current_warehouse_id", "current_location"})
_SPEC_FIELDS = frozenset(
    {
        "weight_kg",
        "length_m",
        "width_m",
        "height_m",
        "volume_m3",
        "requires_permit",
        "requires_escort",
        "requires_special_handling",
        "hazardous",
        "temperature_sensitive",
        "insurance_required",
    }
)


class EquipmentService:
    """Orchestrates Equipment persistence, validation, and event emission."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = EquipmentRepository(session)
        self._categories = EquipmentCategoryRepository(session)
        self._models = EquipmentModelRepository(session)
        self._warehouses = WarehouseRepository(session)
        self._shipments = ShipmentRepository(session)
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
    def _generate_equipment_code() -> str:
        return f"EQP-{uuid.uuid4().hex[:12].upper()}"

    def _require_tenant_owned(self, obj, tenant_id, label, identifier):
        if (
            obj is None
            or getattr(obj, "is_deleted", False)
            or getattr(obj, "tenant_id", None) != tenant_id
        ):
            raise ValidationError(
                f"{label} {identifier} does not exist in this tenant."
            )
        return obj

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_equipment(
        self,
        *,
        equipment_code: Optional[str] = None,
        **data,
    ) -> Equipment:
        """Create and persist a new equipment unit in ``active`` status."""
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        category_id = data["category_id"]
        model_id = data.get("model_id")
        warehouse_id = data.get("current_warehouse_id")

        self._require_tenant_owned(
            self._categories.get_by_id(category_id), tenant_id, "Category", category_id
        )
        if model_id is not None:
            self._require_tenant_owned(
                self._models.get_by_id(model_id), tenant_id, "Model", model_id
            )
        if warehouse_id is not None:
            self._require_tenant_owned(
                self._warehouses.get_by_id(warehouse_id),
                tenant_id,
                "Warehouse",
                warehouse_id,
            )

        code = equipment_code or self._generate_equipment_code()
        if self._repo.get_by_code(code):
            raise ConflictError(
                f"Equipment code '{code}' already exists in this tenant."
            )
        if self._repo.get_by_asset_tag(data["asset_tag"]):
            raise ConflictError(
                f"Asset tag '{data['asset_tag']}' already exists in this tenant."
            )
        serial = data.get("serial_number")
        if serial and self._repo.get_by_serial_number(serial):
            raise ConflictError(
                f"Serial number '{serial}' already exists in this tenant."
            )

        # Status/availability always start active/available on creation.
        data.pop("status", None)
        data.pop("availability_status", None)

        equipment = self._repo.create(
            tenant_id=tenant_id,
            equipment_code=code,
            status=EquipmentStatus.ACTIVE,
            availability_status=EquipmentAvailability.AVAILABLE,
            created_by=actor_id,
            updated_by=actor_id,
            **data,
        )
        self._session.flush()

        self._emit(
            EquipmentCreated(
                equipment_id=equipment.id,
                tenant_id=tenant_id,
                equipment_code=equipment.equipment_code,
                asset_tag=equipment.asset_tag,
                category_id=equipment.category_id,
                model_id=equipment.model_id,
                status=equipment.status.value,
                availability_status=equipment.availability_status.value,
                ownership_type=equipment.ownership_type.value,
            ),
            aggregate_id=equipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(equipment)
        return equipment

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_equipment(
        self, equipment_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Equipment:
        equipment = self._repo.get_by_id(equipment_id)
        if equipment is None:
            raise NotFoundError(f"Equipment {equipment_id} not found.")
        if equipment.is_deleted and not include_deleted:
            raise NotFoundError(f"Equipment {equipment_id} not found.")
        return equipment

    def list_equipment(self, params: EquipmentListParams) -> Page[Equipment]:
        items, total = self._repo.list_equipment(
            q=params.q,
            status=params.status,
            availability_status=params.availability_status,
            category_id=params.category_id,
            model_id=params.model_id,
            current_warehouse_id=params.current_warehouse_id,
            include_deleted=params.include_deleted,
            sort_by=params.sort_by,
            sort_dir=params.sort_dir,
            limit=params.size,
            offset=params.offset,
        )
        pp = PageParams(page=params.page, size=params.size)
        return Page.create(items=items, total=total, params=pp)

    search_equipment = list_equipment

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_equipment(self, equipment_id: uuid.UUID, **data) -> Equipment:
        """Apply partial updates (PATCH). Emits location/spec/general events."""
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        equipment = self._repo.get_by_id_or_raise(equipment_id)
        if equipment.is_deleted:
            raise NotFoundError(f"Equipment {equipment_id} not found (deleted).")
        if EquipmentStateMachine.is_terminal(equipment.status):
            raise ValidationError(
                f"Equipment {equipment_id} is in terminal state "
                f"'{equipment.status.value}' and cannot be edited."
            )

        applied = {k: v for k, v in data.items() if v is not None}

        if "category_id" in applied:
            self._require_tenant_owned(
                self._categories.get_by_id(applied["category_id"]),
                tenant_id,
                "Category",
                applied["category_id"],
            )
        if applied.get("model_id") is not None:
            self._require_tenant_owned(
                self._models.get_by_id(applied["model_id"]),
                tenant_id,
                "Model",
                applied["model_id"],
            )
        if applied.get("current_warehouse_id") is not None:
            self._require_tenant_owned(
                self._warehouses.get_by_id(applied["current_warehouse_id"]),
                tenant_id,
                "Warehouse",
                applied["current_warehouse_id"],
            )
        if "equipment_code" in applied and applied["equipment_code"] != equipment.equipment_code:
            existing = self._repo.get_by_code(applied["equipment_code"])
            if existing is not None and existing.id != equipment.id:
                raise ConflictError(
                    f"Equipment code '{applied['equipment_code']}' already exists."
                )
        if "asset_tag" in applied and applied["asset_tag"] != equipment.asset_tag:
            existing = self._repo.get_by_asset_tag(applied["asset_tag"])
            if existing is not None and existing.id != equipment.id:
                raise ConflictError(
                    f"Asset tag '{applied['asset_tag']}' already exists."
                )

        location_changes = {k: v for k, v in applied.items() if k in _LOCATION_FIELDS}
        spec_changes = {k: v for k, v in applied.items() if k in _SPEC_FIELDS}
        other_changes = {
            k: v
            for k, v in applied.items()
            if k not in _LOCATION_FIELDS and k not in _SPEC_FIELDS
        }

        data["updated_by"] = actor_id
        self._repo.update(equipment, **data)
        self._session.flush()

        if location_changes:
            self._emit(
                EquipmentLocationChanged(
                    equipment_id=equipment.id,
                    tenant_id=tenant_id,
                    changed_fields=_jsonable(location_changes),
                ),
                aggregate_id=equipment.id,
                tenant_id=tenant_id,
            )
        if spec_changes:
            self._emit(
                EquipmentSpecificationChanged(
                    equipment_id=equipment.id,
                    tenant_id=tenant_id,
                    changed_fields=_jsonable(spec_changes),
                ),
                aggregate_id=equipment.id,
                tenant_id=tenant_id,
            )
        if other_changes:
            self._emit(
                EquipmentUpdated(
                    equipment_id=equipment.id,
                    tenant_id=tenant_id,
                    changed_fields=_jsonable(other_changes),
                ),
                aggregate_id=equipment.id,
                tenant_id=tenant_id,
            )

        self._session.commit()
        self._session.refresh(equipment)
        return equipment

    # ------------------------------------------------------------------
    # Generic validated status transition
    # ------------------------------------------------------------------

    def _transition(
        self,
        equipment_id: uuid.UUID,
        new_status: EquipmentStatus,
        *,
        availability: Optional[EquipmentAvailability] = None,
        reason: Optional[str] = None,
        extra_events: Optional[
            List[Callable[[Equipment, EquipmentStatus], object]]
        ] = None,
    ) -> Equipment:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        equipment = self._repo.get_by_id_or_raise(equipment_id)
        if equipment.is_deleted:
            raise NotFoundError(f"Equipment {equipment_id} not found (deleted).")

        previous = equipment.status
        if new_status == previous:
            return equipment  # idempotent no-op

        EquipmentStateMachine.validate_transition(previous, new_status)

        equipment.status = new_status
        if availability is not None:
            equipment.availability_status = availability
        equipment.updated_by = actor_id
        self._session.flush()

        for factory in extra_events or []:
            self._emit(
                factory(equipment, previous),
                aggregate_id=equipment.id,
                tenant_id=tenant_id,
            )
        self._emit(
            EquipmentStatusChanged(
                equipment_id=equipment.id,
                tenant_id=tenant_id,
                previous_status=previous.value,
                new_status=new_status.value,
                reason=reason,
            ),
            aggregate_id=equipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(equipment)
        return equipment

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    def activate_equipment(self, equipment_id: uuid.UUID) -> Equipment:
        return self._transition(
            equipment_id,
            EquipmentStatus.ACTIVE,
            availability=EquipmentAvailability.AVAILABLE,
            extra_events=[
                lambda e, prev: EquipmentActivated(
                    equipment_id=e.id, tenant_id=e.tenant_id, previous_status=prev.value
                )
            ],
        )

    def deactivate_equipment(self, equipment_id: uuid.UUID) -> Equipment:
        return self._transition(
            equipment_id,
            EquipmentStatus.INACTIVE,
            availability=EquipmentAvailability.UNAVAILABLE,
            extra_events=[
                lambda e, prev: EquipmentDeactivated(
                    equipment_id=e.id, tenant_id=e.tenant_id, previous_status=prev.value
                )
            ],
        )

    def reserve_equipment(
        self, equipment_id: uuid.UUID, *, reference: Optional[str] = None
    ) -> Equipment:
        equipment = self._repo.get_by_id_or_raise(equipment_id)
        if not equipment.is_deleted and (
            equipment.availability_status != EquipmentAvailability.AVAILABLE
        ):
            raise ConflictError(
                "Equipment is not available for reservation."
            )
        return self._transition(
            equipment_id,
            EquipmentStatus.RESERVED,
            availability=EquipmentAvailability.RESERVED,
            extra_events=[
                lambda e, prev: EquipmentReserved(
                    equipment_id=e.id,
                    tenant_id=e.tenant_id,
                    previous_status=prev.value,
                    reference=reference,
                )
            ],
        )

    def release_equipment(self, equipment_id: uuid.UUID) -> Equipment:
        return self._transition(
            equipment_id,
            EquipmentStatus.ACTIVE,
            availability=EquipmentAvailability.AVAILABLE,
            extra_events=[
                lambda e, prev: EquipmentReleased(
                    equipment_id=e.id, tenant_id=e.tenant_id, previous_status=prev.value
                )
            ],
        )

    def assign_to_shipment(
        self, equipment_id: uuid.UUID, *, shipment_id: uuid.UUID
    ) -> Equipment:
        """Bind an assignable equipment unit to a shipment (availability=assigned).

        Does not change lifecycle status; validates the shipment is tenant-owned
        and the unit is assignable (not inactive/maintenance/decommissioned).
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        equipment = self._repo.get_by_id_or_raise(equipment_id)
        if equipment.is_deleted:
            raise NotFoundError(f"Equipment {equipment_id} not found (deleted).")
        if not EquipmentStateMachine.is_assignable(equipment.status):
            raise ConflictError(
                f"Equipment in status '{equipment.status.value}' cannot be assigned."
            )

        shipment = self._shipments.get_by_id(shipment_id)
        self._require_tenant_owned(shipment, tenant_id, "Shipment", shipment_id)

        previous_availability = equipment.availability_status
        equipment.availability_status = EquipmentAvailability.ASSIGNED
        equipment.updated_by = actor_id
        self._session.flush()

        self._emit(
            EquipmentAssignedToShipment(
                equipment_id=equipment.id,
                tenant_id=tenant_id,
                shipment_id=shipment_id,
                previous_availability=previous_availability.value,
            ),
            aggregate_id=equipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(equipment)
        return equipment

    def mark_in_transit(self, equipment_id: uuid.UUID) -> Equipment:
        return self._transition(
            equipment_id,
            EquipmentStatus.IN_TRANSIT,
            availability=EquipmentAvailability.ASSIGNED,
            extra_events=[
                lambda e, prev: EquipmentInTransit(
                    equipment_id=e.id, tenant_id=e.tenant_id, previous_status=prev.value
                )
            ],
        )

    def mark_delivered(self, equipment_id: uuid.UUID) -> Equipment:
        return self._transition(
            equipment_id,
            EquipmentStatus.ACTIVE,
            availability=EquipmentAvailability.AVAILABLE,
            extra_events=[
                lambda e, prev: EquipmentDelivered(
                    equipment_id=e.id, tenant_id=e.tenant_id, previous_status=prev.value
                )
            ],
        )

    def start_maintenance(
        self, equipment_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Equipment:
        return self._transition(
            equipment_id,
            EquipmentStatus.UNDER_MAINTENANCE,
            availability=EquipmentAvailability.MAINTENANCE,
            reason=reason,
            extra_events=[
                lambda e, prev: EquipmentMaintenanceStarted(
                    equipment_id=e.id,
                    tenant_id=e.tenant_id,
                    previous_status=prev.value,
                    reason=reason,
                )
            ],
        )

    def complete_maintenance(self, equipment_id: uuid.UUID) -> Equipment:
        return self._transition(
            equipment_id,
            EquipmentStatus.ACTIVE,
            availability=EquipmentAvailability.AVAILABLE,
            extra_events=[
                lambda e, prev: EquipmentMaintenanceCompleted(
                    equipment_id=e.id, tenant_id=e.tenant_id, previous_status=prev.value
                )
            ],
        )

    def decommission_equipment(
        self, equipment_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Equipment:
        return self._transition(
            equipment_id,
            EquipmentStatus.DECOMMISSIONED,
            availability=EquipmentAvailability.UNAVAILABLE,
            reason=reason,
            extra_events=[
                lambda e, prev: EquipmentDecommissioned(
                    equipment_id=e.id,
                    tenant_id=e.tenant_id,
                    previous_status=prev.value,
                    reason=reason,
                )
            ],
        )

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def delete_equipment(self, equipment_id: uuid.UUID) -> None:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        equipment = self._repo.get_by_id_or_raise(equipment_id)
        if equipment.is_deleted:
            raise NotFoundError(f"Equipment {equipment_id} is already deleted.")

        self._repo.soft_delete(equipment, deleted_by=actor_id)
        equipment.updated_by = actor_id
        self._session.flush()

        self._emit(
            EquipmentDeleted(
                equipment_id=equipment.id, tenant_id=tenant_id, deleted_by=actor_id
            ),
            aggregate_id=equipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()

    def restore_equipment(self, equipment_id: uuid.UUID) -> Equipment:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        equipment = self._repo.get_by_id(equipment_id)
        if equipment is None:
            raise NotFoundError(f"Equipment {equipment_id} not found.")
        if not equipment.is_deleted:
            raise ValidationError(
                f"Equipment {equipment_id} is not deleted; nothing to restore."
            )

        self._repo.restore(equipment)
        equipment.updated_by = actor_id
        self._session.flush()

        self._emit(
            EquipmentRestored(equipment_id=equipment.id, tenant_id=tenant_id),
            aggregate_id=equipment.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(equipment)
        return equipment


def _jsonable(data: Dict[str, object]) -> Dict[str, object]:
    from app.events.domain_event import to_jsonable

    return {k: to_jsonable(v) for k, v in data.items()}
