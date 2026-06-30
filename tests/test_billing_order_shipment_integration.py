"""Integration tests proving Billing references Order/Shipment by id with
tenant-owned validation, without owning their lifecycle (Sprint 9)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import PenaltyType
from app.services.exceptions import ValidationError
from app.services.billing_service import BillingService
from billing_sqlite import (
    make_engine,
    seed_customer,
    seed_order,
    seed_shipment,
    seed_tenant_user,
)

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_CUSTOMER = uuid.uuid4()
_ORDER = uuid.uuid4()
_SHIPMENT = uuid.uuid4()

_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT, user_id=_USER)
    seed_customer(_Session, tenant_id=_TENANT, customer_id=_CUSTOMER)
    seed_order(_Session, tenant_id=_TENANT, order_id=_ORDER, customer_id=_CUSTOMER)
    seed_shipment(_Session, tenant_id=_TENANT, client_user_id=_USER, shipment_id=_SHIPMENT, status="delivered")


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.billing_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.billing_service.get_current_user_id", return_value=_USER),
        patch("app.services.billing_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        yield


def _svc():
    return BillingService(_Session())


def test_quote_references_order_and_shipment():
    q = _svc().create_quote(customer_id=_CUSTOMER, order_id=_ORDER, shipment_id=_SHIPMENT,
                            subtotal_amount=Decimal("100"))
    assert q.order_id == _ORDER and q.shipment_id == _SHIPMENT


def test_invoice_references_order_and_shipment():
    inv = _svc().create_invoice(customer_id=_CUSTOMER, order_id=_ORDER, shipment_id=_SHIPMENT, lines=[])
    assert inv.order_id == _ORDER and inv.shipment_id == _SHIPMENT


def test_cross_tenant_order_rejected():
    with pytest.raises(ValidationError):
        _svc().create_invoice(order_id=uuid.uuid4(), lines=[])


def test_cross_tenant_shipment_rejected():
    with pytest.raises(ValidationError):
        _svc().create_quote(shipment_id=uuid.uuid4(), subtotal_amount=Decimal("1"))


def test_penalty_linked_to_order():
    pen = _svc().apply_penalty(penalty_type=PenaltyType.LATE_DELIVERY, amount=Decimal("40"), order_id=_ORDER)
    assert pen.order_id == _ORDER


def test_penalty_linked_to_shipment():
    pen = _svc().apply_penalty(penalty_type=PenaltyType.DAMAGE, amount=Decimal("60"), shipment_id=_SHIPMENT)
    assert pen.shipment_id == _SHIPMENT


def test_cancellation_fee_linked_to_order():
    fee = _svc().apply_cancellation_fee(amount=Decimal("75"), order_id=_ORDER)
    assert fee.penalty_type == PenaltyType.CANCELLATION_FEE and fee.order_id == _ORDER


def test_penalty_cross_tenant_order_rejected():
    with pytest.raises(ValidationError):
        _svc().apply_penalty(penalty_type=PenaltyType.OTHER, amount=Decimal("5"), order_id=uuid.uuid4())
