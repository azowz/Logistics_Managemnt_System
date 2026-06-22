"""CRUD repository for vehicles."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.vehicle import Vehicle
from app.repositories.errors import NotFoundError


class VehicleRepository:
    """Database access for vehicle records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, vehicle_id: str) -> Optional[Vehicle]:
        """Fetch a vehicle by primary key."""
        try:
            vehicle_uuid = uuid.UUID(str(vehicle_id))
        except ValueError:
            return None
        statement = select(Vehicle).where(Vehicle.id == vehicle_uuid)
        return self._session.scalars(statement).first()

    def get_by_plate(self, plate_number: str) -> Optional[Vehicle]:
        """Fetch by unique plate number."""
        statement = select(Vehicle).where(Vehicle.plate_number == plate_number)
        return self._session.scalars(statement).first()

    def list(self, offset: int = 0, limit: int = 100) -> List[Vehicle]:
        """List vehicles with pagination."""
        statement = select(Vehicle).offset(offset).limit(limit)
        return list(self._session.scalars(statement).all())

    def create(self, **data) -> Vehicle:
        """Persist a new vehicle."""
        vehicle = Vehicle(**data)
        self._session.add(vehicle)
        self._session.commit()
        self._session.refresh(vehicle)
        return vehicle

    def update(self, vehicle_id: str, **data) -> Vehicle:
        """Update an existing vehicle; raises if not found."""
        vehicle = self.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle not found.")
        for key, value in data.items():
            if value is not None:
                setattr(vehicle, key, value)
        self._session.commit()
        self._session.refresh(vehicle)
        return vehicle

    def delete(self, vehicle_id: str) -> None:
        """Delete a vehicle by id; raises if not found."""
        vehicle = self.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle not found.")
        self._session.delete(vehicle)
        self._session.commit()
