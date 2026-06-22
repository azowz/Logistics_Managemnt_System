"""CRUD repository for shipments."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shipment import Shipment
from app.repositories.errors import NotFoundError


class ShipmentRepository:
    """Database access for shipment records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, shipment_id: str) -> Optional[Shipment]:
        """Fetch a shipment by primary key."""
        try:
            shipment_uuid = uuid.UUID(str(shipment_id))
        except ValueError:
            return None
        statement = select(Shipment).where(Shipment.id == shipment_uuid)
        return self._session.scalars(statement).first()

    def get_by_reference(self, reference_code: str) -> Optional[Shipment]:
        """Fetch a shipment by its unique reference code."""
        statement = select(Shipment).where(Shipment.reference_code == reference_code)
        return self._session.scalars(statement).first()

    def list(self, offset: int = 0, limit: int = 100) -> List[Shipment]:
        """List shipments with pagination."""
        statement = select(Shipment).offset(offset).limit(limit)
        return list(self._session.scalars(statement).all())

    def create(self, **data) -> Shipment:
        """Persist a new shipment."""
        shipment = Shipment(**data)
        self._session.add(shipment)
        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    def update(self, shipment_id: str, **data) -> Shipment:
        """Update an existing shipment; raises if not found."""
        shipment = self.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError("Shipment not found.")
        for key, value in data.items():
            if value is not None:
                setattr(shipment, key, value)
        self._session.commit()
        self._session.refresh(shipment)
        return shipment

    def delete(self, shipment_id: str) -> None:
        """Delete a shipment by id; raises if not found."""
        shipment = self.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError("Shipment not found.")
        self._session.delete(shipment)
        self._session.commit()
