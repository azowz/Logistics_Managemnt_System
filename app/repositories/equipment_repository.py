"""Repositories for the Equipment & Asset domain (Sprint 6).

Follows the Customer/Order/Shipment pattern:
  * Constructor takes ``Session``; no lifecycle management.
  * **Never commits / rolls back** — the calling service owns the unit of work.
  * Returns aggregates (never HTTP responses); emits no domain events; no FastAPI.
  * RLS scopes every query to the current tenant via the ``after_begin`` GUC
    listener (``app.db.session``).
"""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple, Union

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import EquipmentAvailability, EquipmentStatus
from app.models.equipment import Equipment, EquipmentCategory, EquipmentModel
from app.repositories.errors import NotFoundError


def _coerce_uuid(value: Union[str, uuid.UUID]) -> Optional[uuid.UUID]:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class EquipmentCategoryRepository:
    """Read access to equipment categories (tenant validation support)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, category_id: Union[str, uuid.UUID]) -> Optional[EquipmentCategory]:
        cid = _coerce_uuid(category_id)
        if cid is None:
            return None
        return self._session.get(EquipmentCategory, cid)

    def create(self, **data) -> EquipmentCategory:
        obj = EquipmentCategory(**data)
        self._session.add(obj)
        return obj


class EquipmentModelRepository:
    """Read access to equipment models (tenant validation support)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, model_id: Union[str, uuid.UUID]) -> Optional[EquipmentModel]:
        mid = _coerce_uuid(model_id)
        if mid is None:
            return None
        return self._session.get(EquipmentModel, mid)

    def create(self, **data) -> EquipmentModel:
        obj = EquipmentModel(**data)
        self._session.add(obj)
        return obj


class EquipmentRepository:
    """Persistence boundary for the Equipment aggregate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations (no commit — caller commits)
    # ------------------------------------------------------------------

    def create(self, **data) -> Equipment:
        equipment = Equipment(**data)
        self._session.add(equipment)
        return equipment

    def update(self, equipment: Equipment, **data) -> Equipment:
        for field, value in data.items():
            if value is not None:
                setattr(equipment, field, value)
        return equipment

    # ------------------------------------------------------------------
    # Lookup by primary key
    # ------------------------------------------------------------------

    def get_by_id(self, equipment_id: Union[str, uuid.UUID]) -> Optional[Equipment]:
        eid = _coerce_uuid(equipment_id)
        if eid is None:
            return None
        return self._session.get(Equipment, eid)

    def get_by_id_or_raise(self, equipment_id: Union[str, uuid.UUID]) -> Equipment:
        equipment = self.get_by_id(equipment_id)
        if equipment is None:
            raise NotFoundError(f"Equipment {equipment_id} not found.")
        return equipment

    # ------------------------------------------------------------------
    # Uniqueness guards (tenant-scoped)
    # ------------------------------------------------------------------

    def get_by_code(self, equipment_code: str) -> Optional[Equipment]:
        stmt = select(Equipment).where(
            Equipment.equipment_code == equipment_code,
            Equipment.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def get_by_asset_tag(self, asset_tag: str) -> Optional[Equipment]:
        stmt = select(Equipment).where(
            Equipment.asset_tag == asset_tag,
            Equipment.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    def get_by_serial_number(self, serial_number: str) -> Optional[Equipment]:
        stmt = select(Equipment).where(
            Equipment.serial_number == serial_number,
            Equipment.deleted_at.is_(None),
        )
        return self._session.scalars(stmt).first()

    # ------------------------------------------------------------------
    # Listing with filtering, sorting, pagination
    # ------------------------------------------------------------------

    def list_equipment(
        self,
        *,
        q: Optional[str] = None,
        status: Optional[EquipmentStatus] = None,
        availability_status: Optional[EquipmentAvailability] = None,
        category_id: Optional[uuid.UUID] = None,
        model_id: Optional[uuid.UUID] = None,
        current_warehouse_id: Optional[uuid.UUID] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Equipment], int]:
        """Return ``(items, total)`` honouring all filters, sort, and pagination."""
        stmt = select(Equipment)

        if not include_deleted:
            stmt = stmt.where(Equipment.deleted_at.is_(None))

        if status is not None:
            stmt = stmt.where(Equipment.status == status)
        if availability_status is not None:
            stmt = stmt.where(Equipment.availability_status == availability_status)
        if category_id is not None:
            stmt = stmt.where(Equipment.category_id == category_id)
        if model_id is not None:
            stmt = stmt.where(Equipment.model_id == model_id)
        if current_warehouse_id is not None:
            stmt = stmt.where(Equipment.current_warehouse_id == current_warehouse_id)

        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Equipment.equipment_code.ilike(pattern),
                    Equipment.asset_tag.ilike(pattern),
                    Equipment.name.ilike(pattern),
                    Equipment.serial_number.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = self._session.scalar(count_stmt) or 0

        col = getattr(Equipment, sort_by, Equipment.created_at)
        order_fn = asc if sort_dir == "asc" else desc
        stmt = stmt.order_by(order_fn(col))

        stmt = stmt.limit(limit).offset(offset)
        items = list(self._session.scalars(stmt).all())
        return items, total

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def soft_delete(
        self, equipment: Equipment, *, deleted_by: Optional[uuid.UUID]
    ) -> Equipment:
        equipment.soft_delete()
        equipment.deleted_by = deleted_by
        return equipment

    def restore(self, equipment: Equipment) -> Equipment:
        equipment.restore()
        equipment.deleted_by = None
        return equipment
