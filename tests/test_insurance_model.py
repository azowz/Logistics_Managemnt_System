"""ORM-level tests for insurance/claims models."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.enums import ClaimStatus, ClaimType, InsurancePolicyStatus, InsurancePolicyType
from app.models.insurance import Claim, InsurancePolicy, LiabilityRecord
from insurance_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def _policy(**ov):
    data = dict(tenant_id=_TENANT, policy_number=f"POL-{uuid.uuid4().hex[:8]}", policy_type=InsurancePolicyType.CARGO)
    data.update(ov)
    return InsurancePolicy(**data)


def _claim(**ov):
    data = dict(tenant_id=_TENANT, claim_number=f"CLM-{uuid.uuid4().hex[:8]}", claim_type=ClaimType.SHIPMENT_LOSS)
    data.update(ov)
    return Claim(**data)


def test_policy_defaults(Session):
    s = Session()
    try:
        p = _policy()
        s.add(p); s.commit(); s.refresh(p)
        assert p.status == InsurancePolicyStatus.DRAFT
        assert p.currency_code == "SAR"
        assert p.version == 1
        assert p.covers_shipment is False
    finally:
        s.close()


def test_policy_number_unique(Session):
    s = Session()
    try:
        num = f"POL-DUP-{uuid.uuid4().hex[:6]}"
        s.add(_policy(policy_number=num)); s.commit()
        s.add(_policy(policy_number=num))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback(); s.close()


def test_claim_defaults_and_jsonb(Session):
    s = Session()
    try:
        c = _claim(evidence={"photos": ["a.jpg"]})
        s.add(c); s.commit(); s.refresh(c)
        assert c.status == ClaimStatus.CREATED
        assert c.severity.value == "medium"
        assert c.evidence["photos"] == ["a.jpg"]
        assert c.version == 1
    finally:
        s.close()


def test_claim_number_unique(Session):
    s = Session()
    try:
        num = f"CLM-DUP-{uuid.uuid4().hex[:6]}"
        s.add(_claim(claim_number=num)); s.commit()
        s.add(_claim(claim_number=num))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback(); s.close()


def test_negative_claimed_amount_rejected(Session):
    s = Session()
    try:
        s.add(_claim(claimed_amount=-1))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback(); s.close()


def test_liability_percentage_range(Session):
    s = Session()
    try:
        c = _claim(); s.add(c); s.commit()
        s.add(LiabilityRecord(tenant_id=_TENANT, claim_id=c.id, responsible_party_type="carrier",
                              liability_percentage=150))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback(); s.close()


def test_claim_soft_delete_restore(Session):
    s = Session()
    try:
        c = _claim(); s.add(c); s.commit()
        c.soft_delete(); c.deleted_by = _USER; s.commit(); s.refresh(c)
        assert c.is_deleted
        c.restore(); c.deleted_by = None; s.commit(); s.refresh(c)
        assert not c.is_deleted
    finally:
        s.close()


def test_policy_version_increments(Session):
    s = Session()
    try:
        p = _policy(); s.add(p); s.commit()
        assert p.version == 1
        p.notes = "x"; s.commit(); s.refresh(p)
        assert p.version == 2
    finally:
        s.close()
