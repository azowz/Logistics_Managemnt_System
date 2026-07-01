"""Integration domain-event registration + external mapping/sanitizer tests (no DB)."""

from __future__ import annotations

import uuid

import app.events  # noqa: F401  (registers integration events)
from app.events.registry import event_registry
from app.integrations.event_mapping import (
    ALLOWED_EXTERNAL_EVENT_TYPES,
    SUPPORTED_INTERNAL_EVENT_TYPES,
    external_name,
    is_publishable,
    sanitize_payload,
)

_EVENTS = [
    "IntegrationPartnerCreated", "IntegrationPartnerUpdated", "IntegrationPartnerSuspended",
    "IntegrationPartnerActivated", "PartnerApiKeyCreated", "PartnerApiKeyRevoked",
    "PartnerApiKeyRotated", "WebhookSubscriptionCreated", "WebhookSubscriptionUpdated",
    "WebhookSubscriptionActivated", "WebhookSubscriptionDeactivated", "WebhookDeliveryCreated",
    "WebhookDeliveryAttempted", "WebhookDeliverySucceeded", "WebhookDeliveryFailed",
    "InboundIntegrationEventReceived", "InboundIntegrationEventAccepted", "InboundIntegrationEventRejected",
]


def test_all_18_events_registered_at_v1():
    for name in _EVENTS:
        cls = event_registry.get(name, 1)
        assert cls is not None, name
        assert cls.event_version == 1


def test_event_payload_roundtrip():
    cls = event_registry.get("WebhookDeliveryCreated", 1)
    inst = cls(delivery_id=uuid.uuid4(), tenant_id=uuid.uuid4(), subscription_id=uuid.uuid4(),
               source_event_id=uuid.uuid4(), external_event_type="shipment.delivered")
    back = cls.from_payload(inst.to_payload())
    assert back.external_event_type == "shipment.delivered"
    assert str(back.delivery_id) == str(inst.delivery_id)


def test_external_name_mapping():
    assert external_name("ShipmentDelivered") == "shipment.delivered"
    assert external_name("InvoicePaid") == "invoice.paid"
    assert external_name("ClaimSettled") == "claim.settled"
    assert external_name("DispatchBlockedByCompliance") == "compliance.dispatch_blocked"
    assert external_name("SomethingInternalOnly") is None
    assert not is_publishable("SomethingInternalOnly")


def test_supported_internal_types_map_to_allowed_external():
    assert "ShipmentDelivered" in SUPPORTED_INTERNAL_EVENT_TYPES
    assert "shipment.delivered" in ALLOWED_EXTERNAL_EVENT_TYPES
    assert len(SUPPORTED_INTERNAL_EVENT_TYPES) == len(ALLOWED_EXTERNAL_EVENT_TYPES)


def test_sanitizer_whitelists_and_denies_sensitive_fields():
    payload = {
        "shipment_id": "s1", "status": "delivered", "currency_code": "USD", "total_amount": "10.00",
        "tenant_id": "SECRET-TENANT", "reason": "free text notes", "notes": "internal", "internal_flag": True,
    }
    out = sanitize_payload(payload)
    assert out == {"shipment_id": "s1", "status": "delivered", "currency_code": "USD", "total_amount": "10.00"}
    assert "tenant_id" not in out and "reason" not in out and "notes" not in out
    assert sanitize_payload(None) == {}
