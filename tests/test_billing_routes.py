"""Integration tests for Billing & Settlements API routes (SQLite TestClient)."""

from __future__ import annotations

import types
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes.billing import router as billing_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.session import get_session
from app.models.enums import UserRole
from billing_sqlite import make_engine, seed_claim, seed_customer, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_CUSTOMER = uuid.uuid4()
_CLAIM = uuid.uuid4()

_engine = make_engine()
_TestSession = sessionmaker(bind=_engine, expire_on_commit=False)
_ROLE = {"role": UserRole.ADMIN}


def _sess() -> Iterator:
    s = _TestSession()
    try:
        yield s
    finally:
        s.close()


def _user():
    return types.SimpleNamespace(id=_USER, tenant_id=_TENANT, role=_ROLE["role"], is_active=True)


@pytest.fixture(scope="module")
def client():
    seed_tenant_user(_TestSession, tenant_id=_TENANT, user_id=_USER)
    seed_customer(_TestSession, tenant_id=_TENANT, customer_id=_CUSTOMER)
    seed_claim(_TestSession, tenant_id=_TENANT, claim_id=_CLAIM, status="approved", approved_amount=1000)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(billing_router)
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True, scope="module")
def patch_ctx():
    with (
        patch("app.services.billing_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.billing_service.get_current_user_id", return_value=_USER),
        patch("app.services.billing_service.EventStoreRepository", autospec=True) as MB,
        patch("app.services.settlement_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.settlement_service.get_current_user_id", return_value=_USER),
        patch("app.services.settlement_service.EventStoreRepository", autospec=True) as MS,
    ):
        for M in (MB, MS):
            M.return_value.next_aggregate_version.return_value = 1
            M.return_value.append.return_value = None
        yield


# --- quotes ---------------------------------------------------------------


def _create_quote(client, **ov) -> dict:
    body = {"subtotal_amount": "100", "tax_amount": "15", "discount_amount": "5"}
    body.update(ov)
    r = client.post("/billing/quotes", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_quote_lifecycle(client):
    qid = _create_quote(client)["id"]
    assert client.post(f"/billing/quotes/{qid}/issue").json()["status"] == "issued"
    approved = client.post(f"/billing/quotes/{qid}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "approved"


def test_quote_total_computed(client):
    q = _create_quote(client)
    assert q["total_amount"] == "110.00"


def test_quote_search_before_id(client):
    _create_quote(client, quote_number="QUO-SRCH")
    r = client.get("/billing/quotes/search?q=QUO-SRCH")
    assert r.status_code == 200
    assert any(q["quote_number"] == "QUO-SRCH" for q in r.json()["items"])


def test_quote_invalid_sort_422(client):
    assert client.get("/billing/quotes?sort_by=ssn").status_code == 422


def test_quote_invalid_transition_409(client):
    qid = _create_quote(client)["id"]
    assert client.post(f"/billing/quotes/{qid}/approve").status_code == 409


# --- invoices -------------------------------------------------------------


def _create_invoice(client, **ov) -> dict:
    body = {"customer_id": str(_CUSTOMER), "lines": [
        {"line_type": "transport_fee", "quantity": "1", "unit_price": "200", "tax_rate": "0"}]}
    body.update(ov)
    r = client.post("/billing/invoices", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_invoice_create_and_pay_full(client):
    inv = _create_invoice(client)
    assert inv["total_amount"] == "200.00"
    iid = inv["id"]
    assert client.post(f"/billing/invoices/{iid}/issue").json()["status"] == "issued"
    pay = client.post(f"/billing/invoices/{iid}/payments", json={"amount": "200", "method": "cash"})
    assert pay.status_code == 201
    assert client.get(f"/billing/invoices/{iid}").json()["status"] == "paid"


def test_invoice_partial_payment(client):
    iid = _create_invoice(client)["id"]
    client.post(f"/billing/invoices/{iid}/issue")
    client.post(f"/billing/invoices/{iid}/payments", json={"amount": "50", "method": "card"})
    assert client.get(f"/billing/invoices/{iid}").json()["status"] == "partially_paid"
    lines = client.get(f"/billing/invoices/{iid}/lines").json()
    assert len(lines) == 1
    pays = client.get(f"/billing/invoices/{iid}/payments").json()
    assert len(pays) == 1


def test_invoice_lines_before_id_routing(client):
    # literal sub-path /lines resolves under {invoice_id}; just assert 200 shape
    iid = _create_invoice(client)["id"]
    assert client.get(f"/billing/invoices/{iid}/lines").status_code == 200


def test_invoice_payment_over_balance_422(client):
    iid = _create_invoice(client)["id"]
    client.post(f"/billing/invoices/{iid}/issue")
    r = client.post(f"/billing/invoices/{iid}/payments", json={"amount": "9999", "method": "cash"})
    assert r.status_code == 422


def test_invoice_void_paid_requires_override(client):
    iid = _create_invoice(client)["id"]
    client.post(f"/billing/invoices/{iid}/issue")
    client.post(f"/billing/invoices/{iid}/payments", json={"amount": "200", "method": "cash"})
    assert client.post(f"/billing/invoices/{iid}/void", json={}).status_code == 422
    ok = client.post(f"/billing/invoices/{iid}/void", json={"reason": "x", "allow_override": True})
    assert ok.status_code == 200 and ok.json()["status"] == "voided"


def test_invoice_search_before_id(client):
    _create_invoice(client, invoice_number="INV-SRCH")
    r = client.get("/billing/invoices/search?q=INV-SRCH")
    assert r.status_code == 200
    assert any(i["invoice_number"] == "INV-SRCH" for i in r.json()["items"])


# --- settlements ----------------------------------------------------------


def _create_settlement(client, **ov) -> dict:
    body = {"settlement_type": "claim_payout", "claim_id": str(_CLAIM), "amount": "800"}
    body.update(ov)
    r = client.post("/billing/settlements", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_settlement_full_lifecycle(client):
    sid = _create_settlement(client)["id"]
    assert client.post(f"/billing/settlements/{sid}/submit").json()["status"] == "pending_approval"
    assert client.post(f"/billing/settlements/{sid}/approve").json()["status"] == "approved"
    assert client.post(f"/billing/settlements/{sid}/settle").json()["status"] == "settled"


def test_settlement_payout_after_approval(client):
    sid = _create_settlement(client)["id"]
    client.post(f"/billing/settlements/{sid}/submit")
    client.post(f"/billing/settlements/{sid}/approve")
    po = client.post(f"/billing/settlements/{sid}/payouts", json={"amount": "800", "method": "bank_transfer"})
    assert po.status_code == 201
    assert len(client.get(f"/billing/settlements/{sid}/payouts").json()) == 1


def test_settlement_over_claim_amount_422(client):
    r = client.post("/billing/settlements", json={"settlement_type": "claim_payout",
                                                  "claim_id": str(_CLAIM), "amount": "5000"})
    assert r.status_code == 422


def test_settlement_search_before_id(client):
    _create_settlement(client, settlement_number="STL-SRCH")
    r = client.get("/billing/settlements/search?q=STL-SRCH")
    assert r.status_code == 200
    assert any(x["settlement_number"] == "STL-SRCH" for x in r.json()["items"])


# --- penalties ------------------------------------------------------------


def test_penalty_create_and_list(client):
    r = client.post("/billing/penalties", json={"penalty_type": "late_delivery", "amount": "30"})
    assert r.status_code == 201
    assert client.get("/billing/penalties?penalty_type=late_delivery").status_code == 200


def test_cancellation_fee_via_penalty_route(client):
    order = uuid.uuid4()
    # order not seeded -> cross-tenant/unknown ref rejected (422)
    r = client.post("/billing/penalties", json={"penalty_type": "cancellation_fee", "amount": "30",
                                                "order_id": str(order)})
    assert r.status_code == 422


# --- RBAC -----------------------------------------------------------------


def test_rbac_client_cannot_create_invoice(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.post("/billing/invoices", json={"customer_id": str(_CUSTOMER), "lines": []}).status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_rbac_client_can_read_invoices(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.get("/billing/invoices").status_code == 200
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_rbac_manager_cannot_approve_settlement(client):
    sid = _create_settlement(client)["id"]
    client.post(f"/billing/settlements/{sid}/submit")
    _ROLE["role"] = UserRole.MANAGER
    try:
        assert client.post(f"/billing/settlements/{sid}/approve").status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN
