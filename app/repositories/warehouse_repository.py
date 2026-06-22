"""CRUD repository for warehouses."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.warehouse import Warehouse
from app.repositories.errors import NotFoundError


class WarehouseRepository:
    """Database access for warehouse records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, warehouse_id: str) -> Optional[Warehouse]:
        """Fetch a warehouse by primary key."""
        try:
            warehouse_uuid = uuid.UUID(str(warehouse_id))
        except ValueError:
            return None
        statement = select(Warehouse).where(Warehouse.id == warehouse_uuid)
        return self._session.scalars(statement).first()

    def get_by_code(self, code: str) -> Optional[Warehouse]:
        """Fetch a warehouse by unique code."""
        statement = select(Warehouse).where(Warehouse.code == code)
        return self._session.scalars(statement).first()

    def list(self, offset: int = 0, limit: int = 100) -> List[Warehouse]:
        """List warehouses with pagination."""
        statement = select(Warehouse).offset(offset).limit(limit)
        return list(self._session.scalars(statement).all())

    def create(self, **data) -> Warehouse:
        """Persist a new warehouse."""
        warehouse = Warehouse(**data)
        self._session.add(warehouse)
        self._session.commit()
        self._session.refresh(warehouse)
        return warehouse

    def update(self, warehouse_id: str, **data) -> Warehouse:
        """Update an existing warehouse; raises if not found."""
        warehouse = self.get_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError("Warehouse not found.")
        for key, value in data.items():
            if value is not None:
                setattr(warehouse, key, value)
        self._session.commit()
        self._session.refresh(warehouse)
        return warehouse

    def delete(self, warehouse_id: str) -> None:
        """Delete a warehouse by id; raises if not found."""
        warehouse = self.get_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError("Warehouse not found.")
        self._session.delete(warehouse)
        self._session.commit()
