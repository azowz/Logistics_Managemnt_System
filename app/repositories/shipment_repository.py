"""Repository for the Shipment aggregate.

Refactored in Sprint 5 to match the ``CustomerRepository`` / ``OrderRepository``
pattern:
  * Constructor takes ``Session``; no lifecycle management.
  * **Never commits** — the calling service owns the unit of work.
  * Returns aggregates (never HTTP responses); emits no domain events.
  * RLS scopes every query to the current tenant via the ``after_begin`` GUC
    listener (``app.db.session``).

A small set of legacy methods (``get_by_reference``, ``list``) are preserved
for backward compatibility with the mobile driver flow and existing callers.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple, Union

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import ShipmentPriority, ShipmentStatus
from app.models.shipment import Shipment
from app.repositories.errors import NotFoundError

# Statuses that count as an *active* (in-flight) assignment for driver/vehicle
# exclusivity (a committed assignment).
ACTIVE_ASSIGNMENT_STATUSES: Tuple[ShipmentStatus, ...] = (
    ShipmentStatus.ASSIGNED,
    ShipmentStatus.PICKED_UP,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.DELAYED,
)

# Non-terminal statuses — an equipment unit referenced by any such shipment is
# considered "in use" for equipment exclusivity (broader than the committed set,
# because a unit is reserved to a shipment from the moment it is created).
NON_TERMINAL_STATUSES: Tuple[ShipmentStatus, ...] = (
    ShipmentStatus.CREATED,
    ShipmentStatus.READY,
    ShipmentStatus.ASSIGNED,
    ShipmentStatus.PICKED_UP,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.DELAYED,
)


def _coerce_uuid(value: Union[str, uuid.UUID]) -> Optional[uuid.UUID]:
    """Best-effort coercion of a value to ``uuid.UUID`` (``None`` if invalid)."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class ShipmentRepository:
    """Persistence boundary for the Shipment aggregate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations (no commit — caller commits)
    # ------------------------------------------------------------------

    def create(self, **data) -> Shipment:
        """Instantiate and stage a new Shipment; caller must commit."""
        shipment = Shipment(**data)
        self._session.add(shipment)
        return shipment

    def update(self, shipment: Shipment, **data) -> Shipment:
        """Apply non-None field updates to an existing Shipment in-place."""
        for field, value in data.items():
            if value is not None:
                setattr(shipment, field, value)
        return shipment

    # ------------------------------------------------------------------
    # Lookup by primary key
    # ------------------------------------------------------------------

    def get_by_id(self, shipment_id: Union[str, uuid.UUID]) -> Optional[Shipment]:
        """Return a shipment by PK, or ``None`` if not found / malformed id."""
        shipment_uuid = _coerce_uuid(shipment_id)
        if shipment_uuid is None:
            return None
        return self._session.get(Shipment, shipment_uuid)

    def get_by_id_or_raise(self, shipment_id: Union[str, uuid.UUID]) -> Shipment:
        """Return a shipment by PK, raising :exc:`NotFoundError` if absent."""
        shipment = self.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        return shipment

    # ------------------------------------------------------------------
    # Uniqueness guard (tenant-scoped)
    # ------------------------------------------------------------------

    def get_by_reference_code(self, reference_code: str) -> Optional[Shipment]:
        """Return the active shipment with the given reference in the tenant."""
        stmt = select(Shipment).where(
            Shipment.reference_code == reference_code,
            Shipment.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def get_by_reference(self, reference_code: str) -> Optional[Shipment]:
        """Legacy alias for :meth:`get_by_reference_code` (any soft-delete state)."""
        stmt = select(Shipment).where(Shipment.reference_code == reference_code)
        return self._session.scalars(stmt).first()

    # ------------------------------------------------------------------
    # Active-assignment exclusivity queries
    # ------------------------------------------------------------------

    def has_active_driver_assignment(
        self, driver_id: uuid.UUID, *, exclude_shipment_id: Optional[uuid.UUID] = None
    ) -> bool:
        """Return ``True`` if the driver is bound to another in-flight shipment."""
        stmt = select(func.count(Shipment.id)).where(
            Shipment.driver_id == driver_id,
            Shipment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
            Shipment.deleted_at.is_(None),
        )
        if exclude_shipment_id is not None:
            stmt = stmt.where(Shipment.id != exclude_shipment_id)
        return (self._session.scalar(stmt) or 0) > 0

    def has_active_vehicle_assignment(
        self, vehicle_id: uuid.UUID, *, exclude_shipment_id: Optional[uuid.UUID] = None
    ) -> bool:
        """Return ``True`` if the vehicle is bound to another in-flight shipment."""
        stmt = select(func.count(Shipment.id)).where(
            Shipment.vehicle_id == vehicle_id,
            Shipment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
            Shipment.deleted_at.is_(None),
        )
        if exclude_shipment_id is not None:
            stmt = stmt.where(Shipment.id != exclude_shipment_id)
        return (self._session.scalar(stmt) or 0) > 0

    def has_active_equipment_assignment(
        self, equipment_id: uuid.UUID, *, exclude_shipment_id: Optional[uuid.UUID] = None
    ) -> bool:
        """Return ``True`` if the equipment is bound to another non-terminal shipment."""
        stmt = select(func.count(Shipment.id)).where(
            Shipment.equipment_id == equipment_id,
            Shipment.status.in_(NON_TERMINAL_STATUSES),
            Shipment.deleted_at.is_(None),
        )
        if exclude_shipment_id is not None:
            stmt = stmt.where(Shipment.id != exclude_shipment_id)
        return (self._session.scalar(stmt) or 0) > 0

    # ------------------------------------------------------------------
    # Listing with filtering, sorting, pagination
    # ------------------------------------------------------------------

    def list_shipments(
        self,
        *,
        q: Optional[str] = None,
        status: Optional[ShipmentStatus] = None,
        priority: Optional[ShipmentPriority] = None,
        driver_id: Optional[uuid.UUID] = None,
        vehicle_id: Optional[uuid.UUID] = None,
        order_id: Optional[uuid.UUID] = None,
        client_id: Optional[uuid.UUID] = None,
        origin_warehouse_id: Optional[uuid.UUID] = None,
        destination_warehouse_id: Optional[uuid.UUID] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Shipment], int]:
        """Return ``(items, total)`` honouring all filters, sort, and pagination.

        ``total`` counts ALL matching rows (ignoring limit/offset) so callers can
        build the :class:`~app.common.pagination.Page` envelope.
        """
        stmt = select(Shipment)

        if not include_deleted:
            stmt = stmt.where(Shipment.deleted_at.is_(None))

        if status is not None:
            stmt = stmt.where(Shipment.status == status)
        if priority is not None:
            stmt = stmt.where(Shipment.priority == priority)
        if driver_id is not None:
            stmt = stmt.where(Shipment.driver_id == driver_id)
        if vehicle_id is not None:
            stmt = stmt.where(Shipment.vehicle_id == vehicle_id)
        if order_id is not None:
            stmt = stmt.where(Shipment.order_id == order_id)
        if client_id is not None:
            stmt = stmt.where(Shipment.client_id == client_id)
        if origin_warehouse_id is not None:
            stmt = stmt.where(Shipment.origin_warehouse_id == origin_warehouse_id)
        if destination_warehouse_id is not None:
            stmt = stmt.where(Shipment.destination_warehouse_id == destination_warehouse_id)

        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Shipment.reference_code.ilike(pattern),
                    Shipment.cargo_type.ilike(pattern),
                    Shipment.cargo_description.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = self._session.scalar(count_stmt) or 0

        col = getattr(Shipment, sort_by, Shipment.created_at)
        order_fn = asc if sort_dir == "asc" else desc
        stmt = stmt.order_by(order_fn(col))

        stmt = stmt.limit(limit).offset(offset)
        items = list(self._session.scalars(stmt).all())
        return items, total

    def list(self, offset: int = 0, limit: int = 100) -> List[Shipment]:
        """Legacy: list non-deleted shipments with simple offset pagination."""
        stmt = select(Shipment).where(Shipment.deleted_at.is_(None)).offset(offset).limit(limit)
        return list(self._session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def soft_delete(self, shipment: Shipment, *, deleted_by: Optional[uuid.UUID]) -> Shipment:
        """Mark a shipment as soft-deleted; caller must commit."""
        shipment.soft_delete()  # sets deleted_at via SoftDeleteMixin
        shipment.deleted_by = deleted_by
        return shipment

    def restore(self, shipment: Shipment) -> Shipment:
        """Clear soft-delete markers; caller must commit."""
        shipment.restore()  # clears deleted_at via SoftDeleteMixin
        shipment.deleted_by = None
        return shipment
