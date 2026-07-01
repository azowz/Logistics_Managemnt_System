"""Domain models package.

Importing this package registers every model class on ``Base.metadata`` so that
``Base.metadata.create_all()`` (tests, migrations) and ``alembic autogenerate``
see the complete schema without callers having to remember per-model imports.
"""

from app.models.tenant import Tenant  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.driver import Driver  # noqa: F401
from app.models.vehicle import Vehicle  # noqa: F401
from app.models.warehouse import Warehouse  # noqa: F401
from app.models.shipment import Shipment  # noqa: F401
from app.models.shipment_tracking_event import ShipmentTrackingEvent  # noqa: F401
from app.models.event_store import EventStore, ProcessedEvent, DeadLetterEvent, OutboxRelayState  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.customer import Customer  # noqa: F401
from app.models.order import Order  # noqa: F401
from app.models.equipment import (  # noqa: F401
    Equipment,
    EquipmentCategory,
    EquipmentModel,
)
from app.models.compliance import (  # noqa: F401
    AxleWeightProfile,
    ComplianceCheck,
    Escort,
    OperatorCertification,
    Permit,
    RouteRestriction,
)
from app.models.insurance import (  # noqa: F401
    Claim,
    CoverageRule,
    DamageReport,
    InsurancePolicy,
    LiabilityRecord,
)
from app.models.billing import (  # noqa: F401
    Invoice,
    InvoiceLine,
    Payment,
    Payout,
    Penalty,
    Quote,
    Settlement,
)
from app.models.notification import (  # noqa: F401
    Notification,
    NotificationDeliveryAttempt,
    NotificationTemplate,
)
from app.models.projection import (  # noqa: F401
    ARAgingProjection,
    ClaimsMetricsProjection,
    ComplianceMetricsProjection,
    FinancialSummaryProjection,
    NotificationDeliverabilityProjection,
    OperationsDashboardProjection,
    ProjectionHealth,
    ShipmentPerformanceProjection,
)
from app.models.integration import (  # noqa: F401
    InboundIntegrationEvent,
    IntegrationPartner,
    PartnerApiKey,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)

__all__ = [
    "Tenant",
    "User",
    "Driver",
    "Vehicle",
    "Warehouse",
    "Shipment",
    "ShipmentTrackingEvent",
    "EventStore",
    "ProcessedEvent",
    "DeadLetterEvent",
    "OutboxRelayState",
    "AuditLog",
    "Customer",
    "Order",
    "Equipment",
    "EquipmentCategory",
    "EquipmentModel",
    "Permit",
    "Escort",
    "RouteRestriction",
    "AxleWeightProfile",
    "ComplianceCheck",
    "OperatorCertification",
    "InsurancePolicy",
    "CoverageRule",
    "Claim",
    "DamageReport",
    "LiabilityRecord",
    "Quote",
    "Invoice",
    "InvoiceLine",
    "Payment",
    "Settlement",
    "Payout",
    "Penalty",
    "NotificationTemplate",
    "Notification",
    "NotificationDeliveryAttempt",
    "ProjectionHealth",
    "ShipmentPerformanceProjection",
    "FinancialSummaryProjection",
    "ARAgingProjection",
    "ClaimsMetricsProjection",
    "ComplianceMetricsProjection",
    "NotificationDeliverabilityProjection",
    "OperationsDashboardProjection",
]
