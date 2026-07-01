"""Internal-event → external-webhook-event mapping and payload sanitization.

The webhook consumer must never leak raw internal payloads to partners. Two guards:

1. **Name mapping** — only internal event types present in :data:`EXTERNAL_EVENT_MAP`
   are publishable, under a stable external name (``shipment.delivered`` etc.). Any
   other internal event is ignored (returns ``None``).
2. **Field whitelist** — :func:`sanitize_payload` keeps only the non-sensitive keys in
   :data:`SAFE_FIELDS` (ids, statuses, codes, amounts-as-strings, timestamps). Free-text
   fields (``reason``, ``notes``, ``error_message``, response bodies) and internal
   plumbing (``tenant_id``) are deny-by-default — they are simply not on the allow-list.
"""

from __future__ import annotations

from typing import Optional

# Internal DomainEvent.event_type → external webhook event name.
EXTERNAL_EVENT_MAP: dict[str, str] = {
    # Shipment
    "ShipmentCreated": "shipment.created",
    "ShipmentAssigned": "shipment.assigned",
    "ShipmentInTransit": "shipment.in_transit",
    "ShipmentDelayed": "shipment.delayed",
    "ShipmentDelivered": "shipment.delivered",
    "ShipmentFailed": "shipment.failed",
    "ShipmentCancelled": "shipment.cancelled",
    # Compliance / permits
    "DispatchBlockedByCompliance": "compliance.dispatch_blocked",
    "DispatchClearedByCompliance": "compliance.dispatch_cleared",
    "PermitApproved": "permit.approved",
    "PermitRejected": "permit.rejected",
    "PermitExpired": "permit.expired",
    # Claims
    "ClaimCreated": "claim.created",
    "ClaimApproved": "claim.approved",
    "ClaimRejected": "claim.rejected",
    "ClaimSettled": "claim.settled",
    # Billing
    "InvoiceIssued": "invoice.issued",
    "InvoicePaid": "invoice.paid",
    "PaymentFailed": "payment.failed",
    "SettlementApproved": "settlement.approved",
    "SettlementSettled": "settlement.settled",
    # Notifications
    "NotificationFailed": "notification.failed",
}

# The consumer subscribes to exactly these internal event types.
SUPPORTED_INTERNAL_EVENT_TYPES = frozenset(EXTERNAL_EVENT_MAP.keys())

# The set of external names partners are allowed to subscribe to.
ALLOWED_EXTERNAL_EVENT_TYPES = frozenset(EXTERNAL_EVENT_MAP.values())

# Deny-by-default field allow-list for outbound payloads. Only these keys are copied
# from an internal event payload into the external webhook payload.
SAFE_FIELDS = frozenset({
    # shipment
    "shipment_id", "reference_code", "client_id", "customer_id", "order_id",
    "origin_warehouse_id", "destination_warehouse_id", "driver_id", "vehicle_id",
    "status", "previous_status", "new_status", "priority",
    "delivered_at", "picked_up_at", "planned_delivery_at", "delay_minutes",
    # compliance / permits
    "permit_id", "permit_type", "permit_number",
    # claims
    "claim_id", "claim_number", "claim_type", "approved_amount", "claimed_amount", "cycle_days",
    # billing
    "invoice_id", "invoice_number", "total_amount", "payment_id", "amount", "method",
    "settlement_id", "settlement_number", "settlement_type", "currency_code",
    # notifications
    "notification_id", "channel", "source_event_type",
})


def external_name(internal_event_type: str) -> Optional[str]:
    """Return the external webhook name for an internal event type, or ``None``."""
    return EXTERNAL_EVENT_MAP.get(internal_event_type)


def is_publishable(internal_event_type: str) -> bool:
    """Whether an internal event type has an external mapping (is publishable)."""
    return internal_event_type in EXTERNAL_EVENT_MAP


def sanitize_payload(payload: Optional[dict]) -> dict:
    """Whitelist-filter an internal payload down to non-sensitive external fields."""
    if not payload:
        return {}
    return {k: v for k, v in payload.items() if k in SAFE_FIELDS}


__all__ = [
    "EXTERNAL_EVENT_MAP",
    "SUPPORTED_INTERNAL_EVENT_TYPES",
    "ALLOWED_EXTERNAL_EVENT_TYPES",
    "SAFE_FIELDS",
    "external_name",
    "is_publishable",
    "sanitize_payload",
]
