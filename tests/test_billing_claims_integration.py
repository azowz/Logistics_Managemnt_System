"""Integration tests proving Billing consumes Claims outcomes without owning the
claim lifecycle (Sprint 9, context #18 ↔ #17)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import ClaimStatus, SettlementStatus, SettlementType
from app.models.insurance import Claim
from app.services.exceptions import StatusTransitionError, ValidationError
from app.services.settlement_service import SettlementService
from billing_sqlite import make_engine, seed_claim, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()

_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT, user_id=_USER)


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.settlement_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.settlement_service.get_current_user_id", return_value=_USER),
        patch("app.services.settlement_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        yield


def _svc():
    return SettlementService(_Session())


def test_settlement_references_approved_claim():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    stl = _svc().create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("600"))
    assert stl.claim_id == cid and stl.status == SettlementStatus.DRAFT


def test_settlement_rejects_unapproved_claim():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="created", approved_amount=0)
    with pytest.raises(ValidationError):
        _svc().create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("1"))


def test_settlement_rejects_cross_tenant_claim():
    other = uuid.uuid4()
    cid = uuid.uuid4()
    seed_tenant_user(_Session, tenant_id=other, user_id=uuid.uuid4())
    seed_claim(_Session, tenant_id=other, claim_id=cid, status="approved", approved_amount=1000)
    with pytest.raises(ValidationError):
        _svc().create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("1"))


def test_settlement_amount_bounded_by_approved_claim_amount():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=500)
    with pytest.raises(ValidationError):
        _svc().create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("600"))


def test_settlement_can_be_settled_after_approval():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    svc = _svc()
    stl = svc.create_settlement(settlement_type=SettlementType.CLAIM_PAYOUT, claim_id=cid, amount=Decimal("400"))
    svc.submit_settlement_for_approval(stl.id)
    svc.approve_settlement(stl.id)
    settled = svc.settle_settlement(stl.id)
    assert settled.status == SettlementStatus.SETTLED


def test_claim_lifecycle_unchanged_by_settlement():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="approved", approved_amount=1000)
    svc = _svc()
    stl = svc.consume_claim_settlement(claim_id=cid, amount=Decimal("700"))
    # the claim row is untouched — Billing never mutates the claim aggregate
    s = _Session()
    try:
        claim = s.get(Claim, cid)
        assert claim.status == ClaimStatus.APPROVED
        assert claim.approved_amount == Decimal("1000.00")
    finally:
        s.close()
    assert stl.amount == Decimal("700.00")


def test_offset_settlement_also_bounded():
    cid = uuid.uuid4()
    seed_claim(_Session, tenant_id=_TENANT, claim_id=cid, status="settled", approved_amount=200)
    with pytest.raises(ValidationError):
        _svc().create_settlement(settlement_type=SettlementType.CLAIM_OFFSET, claim_id=cid, amount=Decimal("250"))
