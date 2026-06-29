"""Tests for Customer domain events.

Covers:
  * Frozen dataclass invariant — immutability.
  * `event_type` / `event_version` class variables.
  * Process-wide registry entry (via ``@register_event``).
  * `EventEnvelope.create()` wrapping — payload survives round-trip.
  * All 9 events are registered.
"""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

from app.events.customer_events import (
    CustomerActivated,
    CustomerAddressUpdated,
    CustomerContactUpdated,
    CustomerCreated,
    CustomerDeleted,
    CustomerRestored,
    CustomerStatusChanged,
    CustomerSuspended,
    CustomerUpdated,
)
from app.events.envelope import EventEnvelope
from app.events.registry import event_registry

TENANT = uuid.uuid4()
CUSTOMER = uuid.uuid4()
USER = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _customer_created() -> CustomerCreated:
    return CustomerCreated(
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        code="CUST-001",
        company_name="Mesaar LLC",
        customer_type="corporate",
        status="active",
    )


def _wrap(event) -> EventEnvelope:
    return EventEnvelope.create(
        event,
        tenant_id=TENANT,
        aggregate_id=CUSTOMER,
        aggregate_version=1,
        aggregate_type="Customer",
        user_id=USER,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_cls",
    [
        CustomerCreated,
        CustomerUpdated,
        CustomerActivated,
        CustomerSuspended,
        CustomerDeleted,
        CustomerRestored,
        CustomerContactUpdated,
        CustomerAddressUpdated,
        CustomerStatusChanged,
    ],
)
def test_all_events_registered(event_cls):
    """Each event class should appear in the process-wide registry."""
    assert event_registry.is_registered(event_cls.event_type), (
        f"{event_cls.__name__} not found in event_registry"
    )


# ---------------------------------------------------------------------------
# Frozen / immutability
# ---------------------------------------------------------------------------


def test_customer_created_is_frozen():
    event = _customer_created()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        event.code = "HACK"  # type: ignore[misc]


def test_customer_updated_is_frozen():
    event = CustomerUpdated(
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        changed_fields={"company_name": "New Name"},
    )
    with pytest.raises((FrozenInstanceError, AttributeError)):
        event.changed_fields = {}  # type: ignore[misc]


def test_customer_deleted_is_frozen():
    event = CustomerDeleted(
        customer_id=CUSTOMER, tenant_id=TENANT, deleted_by=USER
    )
    with pytest.raises((FrozenInstanceError, AttributeError)):
        event.deleted_by = None  # type: ignore[misc]


# ---------------------------------------------------------------------------
# event_type + event_version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_cls, expected_type",
    [
        (CustomerCreated, "CustomerCreated"),
        (CustomerUpdated, "CustomerUpdated"),
        (CustomerActivated, "CustomerActivated"),
        (CustomerSuspended, "CustomerSuspended"),
        (CustomerDeleted, "CustomerDeleted"),
        (CustomerRestored, "CustomerRestored"),
        (CustomerContactUpdated, "CustomerContactUpdated"),
        (CustomerAddressUpdated, "CustomerAddressUpdated"),
        (CustomerStatusChanged, "CustomerStatusChanged"),
    ],
)
def test_event_type_string(event_cls, expected_type):
    assert event_cls.event_type == expected_type


def test_all_events_have_version_one():
    for cls in [
        CustomerCreated,
        CustomerUpdated,
        CustomerActivated,
        CustomerSuspended,
        CustomerDeleted,
        CustomerRestored,
        CustomerContactUpdated,
        CustomerAddressUpdated,
        CustomerStatusChanged,
    ]:
        assert cls.event_version == 1, f"{cls.__name__}.event_version != 1"


# ---------------------------------------------------------------------------
# EventEnvelope wrapping
# ---------------------------------------------------------------------------


def test_customer_created_envelope_preserves_payload():
    event = _customer_created()
    envelope = _wrap(event)

    assert envelope.tenant_id == TENANT
    assert envelope.aggregate_id == CUSTOMER
    assert envelope.aggregate_type == "Customer"
    assert envelope.event_type == "CustomerCreated"
    assert envelope.payload["code"] == "CUST-001"
    assert envelope.payload["company_name"] == "Mesaar LLC"


def test_customer_updated_envelope():
    event = CustomerUpdated(
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        changed_fields={"company_name": "New Corp"},
    )
    envelope = _wrap(event)
    assert envelope.event_type == "CustomerUpdated"
    assert envelope.payload["changed_fields"]["company_name"] == "New Corp"


def test_customer_status_changed_envelope():
    event = CustomerStatusChanged(
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        previous_status="active",
        new_status="suspended",
        reason="Non-payment",
    )
    envelope = _wrap(event)
    assert envelope.payload["previous_status"] == "active"
    assert envelope.payload["new_status"] == "suspended"
    assert envelope.payload["reason"] == "Non-payment"


def test_customer_deleted_envelope_nullable_deleted_by():
    event = CustomerDeleted(
        customer_id=CUSTOMER, tenant_id=TENANT, deleted_by=None
    )
    envelope = _wrap(event)
    assert envelope.payload["deleted_by"] is None


def test_customer_suspended_envelope_nullable_reason():
    event = CustomerSuspended(
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        previous_status="active",
        reason=None,
    )
    envelope = _wrap(event)
    assert envelope.payload["reason"] is None


def test_customer_restored_envelope():
    event = CustomerRestored(customer_id=CUSTOMER, tenant_id=TENANT)
    envelope = _wrap(event)
    assert envelope.event_type == "CustomerRestored"
    assert envelope.aggregate_version == 1


def test_customer_contact_updated_envelope():
    event = CustomerContactUpdated(
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        changed_fields={"primary_email": "new@example.com"},
    )
    envelope = _wrap(event)
    assert envelope.event_type == "CustomerContactUpdated"
    assert envelope.payload["changed_fields"]["primary_email"] == "new@example.com"


def test_customer_address_updated_envelope():
    event = CustomerAddressUpdated(
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        changed_fields={"city": "Riyadh", "country": "SA"},
    )
    envelope = _wrap(event)
    assert envelope.event_type == "CustomerAddressUpdated"
    assert envelope.payload["changed_fields"]["city"] == "Riyadh"


# ---------------------------------------------------------------------------
# Registry maps to correct class
# ---------------------------------------------------------------------------


def test_registry_resolves_to_correct_class():
    for cls in [
        CustomerCreated,
        CustomerUpdated,
        CustomerActivated,
        CustomerSuspended,
        CustomerDeleted,
        CustomerRestored,
        CustomerContactUpdated,
        CustomerAddressUpdated,
        CustomerStatusChanged,
    ]:
        resolved = event_registry.get(cls.event_type, cls.event_version)
        assert resolved is cls, (
            f"Registry has {resolved!r} for key '{cls.event_type}', expected {cls!r}"
        )
