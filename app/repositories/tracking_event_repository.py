"""CRUD repository for shipment tracking events."""

from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shipment_tracking_event import ShipmentTrackingEvent
from app.repositories.errors import NotFoundError


class TrackingEventRepository:
    """Database access for tracking events."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, event_id: str) -> Optional[ShipmentTrackingEvent]:
        """Fetch a tracking event by primary key."""
        try:
            event_uuid = uuid.UUID(str(event_id))
        except ValueError:
            return None
        statement = select(ShipmentTrackingEvent).where(ShipmentTrackingEvent.id == event_uuid)
        return self._session.scalars(statement).first()

    def list_for_shipment(
        self,
        shipment_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> List[ShipmentTrackingEvent]:
        """List events for a shipment ordered by event_time."""
        try:
            shipment_uuid = uuid.UUID(str(shipment_id))
        except ValueError:
            return []
        statement = (
            select(ShipmentTrackingEvent)
            .where(ShipmentTrackingEvent.shipment_id == shipment_uuid)
            .order_by(ShipmentTrackingEvent.event_time)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def create(self, **data) -> ShipmentTrackingEvent:
        """Persist a new tracking event."""
        event = ShipmentTrackingEvent(**data)
        self._session.add(event)
        self._session.commit()
        self._session.refresh(event)
        return event

    def delete(self, event_id: str) -> None:
        """Delete a tracking event; raises if not found."""
        event = self.get_by_id(event_id)
        if event is None:
            raise NotFoundError("Tracking event not found.")
        self._session.delete(event)
        self._session.commit()
