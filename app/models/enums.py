"""Domain enums shared by ORM models.

Using `str` mixins keeps database values readable while remaining
JSON-serializable for API responses.
"""

from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    DRIVER = "driver"
    CLIENT = "client"


class VehicleStatus(str, Enum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"


class ShipmentStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    FAILED = "failed"


class TrackingEventType(str, Enum):
    STATUS_UPDATE = "status_update"
    LOCATION_UPDATE = "location_update"
    PROOF_OF_DELIVERY = "proof_of_delivery"
    EXCEPTION = "exception"
