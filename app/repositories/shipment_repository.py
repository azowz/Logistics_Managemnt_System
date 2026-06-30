"""Repository for the Shipment aggregate.

Refactored (Sprint 5) to match the Customer/Order pattern:
  * Constructor takes ``Session``; no lifecycle management.
  * **Never commits** — the calling service owns the unit of work.
  * RLS scopes every query to the current tenant via the ``after_begin`` GUC
    listener (``app.db.session``).

Legacy methods (``get_by_id``, ``get_by_reference``, ``list``) are preserved for
backward compatibility (e.g. ``DriverService``); ``create``/``update`` no longer
commit.
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import ShipmentPriority, ShipmentStatus
from app.models.shipment import Shipment
from app.repositories.errors import NotFoundError


def _as_uuid(value) -> Optional[uuid.UUID]:
    """Best-effort coerce a value to UUID, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


class ShipmentRepository:
    """Database access for shipment records (no commits — service owns UoW)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_by_id(self, shipment_id) -> Optional[Shipment]:
        """Fetch a shipment by primary key (accepts str or UUID)."""
        shipment_uuid = _as_uuid(shipment_id)
        if shipment_uuid is None:
            return None
        return self._session.get(Shipment, shipment_uuid)

    def get_by_id_or_raise(self, shipment_id) -> Shipment:
        """Fetch by PK, raising :exc:`NotFoundError` if absent."""
        shipment = self.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        return shipment

    def get_by_reference(self, reference_code: str) -> Optional[Shipment]:
        """Fetch a shipment by its tenant-unique reference code (legacy alias)."""
        return self.get_by_reference_code(reference_code)

    def get_by_reference_code(self, reference_code: str) -> Optional[Shipment]:
        """Return the (non-deleted) shipment with the given reference code."""
        stmt = select(Shipment).where(
            Shipment.reference_code == reference_code,
            Shipment.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def list(self, offset: int = 0, limit: int = 100) -> List[Shipment]:
        """List non-deleted shipments with pagination (legacy)."""
        stmt = (
            select(Shipment)
            .where(Shipment.deleted_at.is_(None))
            .order_by(desc(Shipment.created_at))
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # Writes (no commit — caller commits)
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

    def soft_delete(self, shipment: Shipment, *, deleted_by: Optional[uuid.UUID]) -> Shipment:
        """Mark a shipment soft-deleted; caller must commit."""
        shipment.soft_delete()
        shipment.deleted_by = deleted_by
        return shipment

    def restore(self, shipment: Shipment) -> Shipment:
        """Clear soft-delete markers; caller must commit."""
        shipment.restore()
        shipment.deleted_by = None
        return shipment

    # ------------------------------------------------------------------
    # Filtered / sorted / paginated listing
    # ------------------------------------------------------------------

    def list_shipments(
        self,
        *,
        q: Optional[str] = None,
        status: Optional[ShipmentStatus] = None,
        priority: Optional[ShipmentPriority] = None,
        client_id: Optional[uuid.UUID] = None,
        driver_id: Optional[uuid.UUID] = None,
        vehicle_id: Optional[uuid.UUID] = None,
        order_id: Optional[uuid.UUID] = None,
        origin_warehouse_id: Optional[uuid.UUID] = None,
        destination_warehouse_id: Optional[uuid.UUID] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Shipment], int]:
        """Return ``(items, total)`` honouring filters, sort, and pagination."""
        stmt = select(Shipment)

        if not include_deleted:
            stmt = stmt.where(Shipment.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Shipment.status == status)
        if priority is not None:
            stmt = stmt.where(Shipment.priority == priority)
        if client_id is not None:
            stmt = stmt.where(Shipment.client_id == client_id)
        if driver_id is not None:
            stmt = stmt.where(Shipment.driver_id == driver_id)
        if vehicle_id is not None:
            stmt = stmt.where(Shipment.vehicle_id == vehicle_id)
        if order_id is not None:
            stmt = stmt.where(Shipment.order_id == order_id)
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
        stmt = stmt.order_by(order_fn(col)).limit(limit).offset(offset)

        items = list(self._session.scalars(stmt).all())
        return items, total

    # ------------------------------------------------------------------
    # Active-assignment queries (exclusivity guards)
    # ------------------------------------------------------------------

    _ACTIVE_STATUSES = (
        ShipmentStatus.CREATED,
        ShipmentStatus.READY,
        ShipmentStatus.ASSIGNED,
        ShipmentStatus.PICKED_UP,
        ShipmentStatus.IN_TRANSIT,
        ShipmentStatus.DELAYED,
    )

    def count_active_for_driver(
        self, driver_id: uuid.UUID, *, exclude_shipment_id: Optional[uuid.UUID] = None
    ) -> int:
        """Count active shipments bound to a driver (for exclusivity checks)."""
        stmt = select(func.count(Shipment.id)).where(
            Shipment.driver_id == driver_id,
            Shipment.status.in_(self._ACTIVE_STATUSES),
            Shipment.deleted_at.is_(None),
        )
        if exclude_shipment_id is not None:
            stmt = stmt.where(Shipment.id != exclude_shipment_id)
        return self._session.scalar(stmt) or 0

    def count_active_for_vehicle(
        self, vehicle_id: uuid.UUID, *, exclude_shipment_id: Optional[uuid.UUID] = None
    ) -> int:
        """Count active shipments bound to a vehicle (for exclusivity checks)."""
        stmt = select(func.count(Shipment.id)).where(
            Shipment.vehicle_id == vehicle_id,
            Shipment.status.in_(self._ACTIVE_STATUSES),
            Shipment.deleted_at.is_(None),
        )
        if exclude_shipment_id is not None:
            stmt = stmt.where(Shipment.id != exclude_shipment_id)
        return self._session.scalar(stmt) or 0
