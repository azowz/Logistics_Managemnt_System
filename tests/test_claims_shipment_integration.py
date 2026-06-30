"""Integration: Claims may reference failed/returned shipments (SQLite)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import ClaimType
from app.services.claims_service import ClaimsService
from app.services.exceptions import ValidationError
from insurance_sqlite import make_engine, seed_active_policy, seed_shipment, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_POLICY = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SL = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SL, tenant_id=_TENANT, user_id=_USER)
    seed_active_policy(SL, tenant_id=_TENANT, policy_id=_POLICY)
    return SL


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.claims_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.claims_service.get_current_user_id", return_value=_USER),
        patch("app.services.claims_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        yield


def test_claim_references_failed_shipment(Session):
    sid = uuid.uuid4()
    seed_shipment(Session, tenant_id=_TENANT, client_user_id=_USER, shipment_id=sid, status="failed")
    s = Session()
    try:
        claim = ClaimsService(s).create_claim(claim_type=ClaimType.SHIPMENT_DAMAGE, shipment_id=sid, policy_id=_POLICY)
        assert claim.shipment_id == sid
    finally:
        s.close()


def test_claim_references_returned_shipment(Session):
    sid = uuid.uuid4()
    seed_shipment(Session, tenant_id=_TENANT, client_user_id=_USER, shipment_id=sid, status="returned")
    s = Session()
    try:
        claim = ClaimsService(s).create_claim(claim_type=ClaimType.SHIPMENT_LOSS, shipment_id=sid, policy_id=_POLICY)
        assert claim.shipment_id == sid
    finally:
        s.close()


def test_cross_tenant_shipment_rejected(Session):
    other = uuid.uuid4()
    from app.models.tenant import Tenant
    s0 = Session()
    s0.add(Tenant(id=other, slug=f"o{other.hex[:6]}", name="O", status="active", isolation_mode="shared"))
    s0.commit(); s0.close()
    sid = uuid.uuid4()
    seed_shipment(Session, tenant_id=other, client_user_id=_USER, shipment_id=sid, status="failed")
    s = Session()
    try:
        with pytest.raises(ValidationError, match="Shipment"):
            ClaimsService(s).create_claim(claim_type=ClaimType.SHIPMENT_LOSS, shipment_id=sid)
    finally:
        s.close()


def test_normal_shipment_unaffected(Session):
    # Creating a claim does not mutate the shipment row.
    sid = uuid.uuid4()
    seed_shipment(Session, tenant_id=_TENANT, client_user_id=_USER, shipment_id=sid, status="failed")
    s = Session()
    try:
        ClaimsService(s).create_claim(claim_type=ClaimType.SHIPMENT_LOSS, shipment_id=sid, policy_id=_POLICY)
    finally:
        s.close()
    from app.models.shipment import Shipment
    s2 = Session()
    try:
        assert s2.get(Shipment, sid).status.value == "failed"
    finally:
        s2.close()
