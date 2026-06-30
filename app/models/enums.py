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
    """Shipment lifecycle states (see app.services.shipment_policies.ShipmentStateMachine).

    Lifecycle:
        created → ready → assigned → picked_up → in_transit → delivered
    with ``delayed`` as an in-transit overlay, ``failed`` allowing ``returned``,
    and ``cancelled`` reachable from any pre-delivery state.

    ``PICKED_UP`` and ``DELAYED`` were introduced in Sprint 5 to align the
    operational lifecycle with the Order domain; older states are preserved for
    backward compatibility.
    """

    CREATED = "created"
    READY = "ready"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    FAILED = "failed"


class ShipmentPriority(str, Enum):
    """Operational priority used for dispatch ordering (Sprint 5).

    Stored as lowercase values (``values_callable``) so the database
    representation matches the Order domain's priority column.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TrackingEventType(str, Enum):
    STATUS_UPDATE = "status_update"
    LOCATION_UPDATE = "location_update"
    PROOF_OF_DELIVERY = "proof_of_delivery"
    EXCEPTION = "exception"


class CustomerType(str, Enum):
    INDIVIDUAL = "individual"
    CORPORATE = "corporate"
    GOVERNMENT = "government"
    SME = "sme"


class CustomerStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CreditStatus(str, Enum):
    GOOD = "good"
    WATCH = "watch"
    BLOCKED = "blocked"


class EquipmentStatus(str, Enum):
    """Equipment unit lifecycle status (see EquipmentStateMachine, Sprint 6).

    Maps onto the docs/08 Part 6 lifecycle: ``under_maintenance`` ≈ Maintenance,
    ``decommissioned`` ≈ OutOfService (terminal).
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNDER_MAINTENANCE = "under_maintenance"
    RESERVED = "reserved"
    IN_TRANSIT = "in_transit"
    DECOMMISSIONED = "decommissioned"


class EquipmentAvailability(str, Enum):
    """Operational availability of an equipment unit (Sprint 6)."""

    AVAILABLE = "available"
    RESERVED = "reserved"
    UNAVAILABLE = "unavailable"
    ASSIGNED = "assigned"
    MAINTENANCE = "maintenance"


class EquipmentOwnershipType(str, Enum):
    """How the tenant holds an equipment unit (Sprint 6)."""

    OWNED = "owned"
    LEASED = "leased"
    CUSTOMER_OWNED = "customer_owned"
    THIRD_PARTY = "third_party"


class PermitStatus(str, Enum):
    """Permit lifecycle status (see PermitStateMachine, Sprint 7).

    Terminal: ``rejected``, ``expired``, ``cancelled``.
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PermitType(str, Enum):
    """Classification of a movement permit (docs/08 Part 2.1)."""

    OVERSIZE = "oversize"
    OVERWEIGHT = "overweight"
    GOVERNMENT = "government"
    MUNICIPAL = "municipal"
    SPECIAL_MOVEMENT = "special_movement"
    SITE_ENTRY = "site_entry"


class EscortType(str, Enum):
    """Type of escort accompanying an oversize/overweight movement."""

    PRIVATE_ESCORT = "private_escort"
    POLICE_ESCORT = "police_escort"
    PILOT_VEHICLE = "pilot_vehicle"
    TECHNICAL_SUPPORT = "technical_support"


class EscortStatus(str, Enum):
    """Lifecycle of an escort plan."""

    PLANNED = "planned"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class RouteRestrictionType(str, Enum):
    """Type of road/route restriction (docs/08 Part 4)."""

    WEIGHT_LIMIT = "weight_limit"
    HEIGHT_LIMIT = "height_limit"
    WIDTH_LIMIT = "width_limit"
    LENGTH_LIMIT = "length_limit"
    TIME_WINDOW = "time_window"
    HAZARDOUS_MATERIAL = "hazardous_material"
    ROAD_CLOSURE = "road_closure"


class ComplianceCheckType(str, Enum):
    """Category of compliance evaluation (docs/08 Part 2.3)."""

    PERMIT_REQUIRED = "permit_required"
    PERMIT_VALIDITY = "permit_validity"
    ESCORT_REQUIRED = "escort_required"
    AXLE_WEIGHT = "axle_weight"
    OVERSIZE = "oversize"
    ROUTE_RESTRICTION = "route_restriction"
    OPERATOR_CERTIFICATION = "operator_certification"
    INSURANCE_REQUIRED = "insurance_required"
    HAZARDOUS_MATERIAL = "hazardous_material"


class ComplianceCheckStatus(str, Enum):
    """Outcome of a compliance check."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    OVERRIDDEN = "overridden"


class OperatorCertificationStatus(str, Enum):
    """Validity status of an operator certification."""

    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class OrderType(str, Enum):
    """Classification of a transport order."""

    STANDARD = "standard"
    EXPRESS = "express"
    SAME_DAY = "same_day"
    ECONOMY = "economy"
    RETURN = "return"


class OrderSource(str, Enum):
    """Channel through which an order originated."""

    WEB = "web"
    MOBILE = "mobile"
    API = "api"
    PHONE = "phone"
    EMAIL = "email"
    WALK_IN = "walk_in"


class OrderPriority(str, Enum):
    """Operational priority used for scheduling and dispatch."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class OrderStatus(str, Enum):
    """Order lifecycle states (see app.services.order_policies.OrderStateMachine).

    Lifecycle:
        draft → submitted → approved → scheduled → assigned → in_transit → delivered
    with ``cancelled`` and ``failed`` as alternative terminal states reachable from
    the in-progress states.
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"
