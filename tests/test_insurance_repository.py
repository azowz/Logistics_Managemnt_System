"""Tests for insurance/claims repositories: no-commit, query helpers, soft-delete."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import ClaimStatus, ClaimType, InsurancePolicyStatus, InsurancePolicyType
from app.repositories.errors import NotFoundError
from app.repositories.insurance_repository import (
    ClaimRepository,
    CoverageRuleRepository,
    DamageReportRepository,
    InsurancePolicyRepository,
    LiabilityRecordRepository,
)
from insurance_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def test_policy_no_commit_and_lookup(Session):
    s = Session()
    try:
        repo = InsurancePolicyRepository(s)
        p = repo.create(tenant_id=_TENANT, policy_number="POL-NC", policy_type=InsurancePolicyType.CARGO,
                        status=InsurancePolicyStatus.ACTIVE)
        pid = p.id
        s.rollback()
        assert repo.get_by_id(pid) is None
        with pytest.raises(NotFoundError):
            repo.get_by_id_or_raise(uuid.uuid4())
    finally:
        s.close()


def test_policy_get_by_number_and_list(Session):
    s = Session()
    try:
        repo = InsurancePolicyRepository(s)
        repo.create(tenant_id=_TENANT, policy_number="POL-FIND", policy_type=InsurancePolicyType.CARGO,
                    status=InsurancePolicyStatus.ACTIVE, provider_name="Acme")
        s.commit()
        assert repo.get_by_number("POL-FIND") is not None
        items, total = repo.list_policies(status=InsurancePolicyStatus.ACTIVE, limit=1)
        assert total >= 1 and len(items) == 1
        found, _ = repo.list_policies(q="Acme")
        assert any(p.provider_name == "Acme" for p in found)
    finally:
        s.close()


def test_coverage_rules_for_policy(Session):
    s = Session()
    try:
        prepo = InsurancePolicyRepository(s)
        policy = prepo.create(tenant_id=_TENANT, policy_number=f"POL-{uuid.uuid4().hex[:6]}",
                              policy_type=InsurancePolicyType.CARGO)
        s.commit()
        crepo = CoverageRuleRepository(s)
        crepo.create(tenant_id=_TENANT, policy_id=policy.id, coverage_type="shipment_loss", active=True)
        s.commit()
        assert len(crepo.get_rules_for_policy(policy.id)) == 1
        assert len(crepo.get_rules_for_policy(policy.id, active_only=True)) == 1
    finally:
        s.close()


def test_claim_lookups(Session):
    s = Session()
    try:
        prepo = InsurancePolicyRepository(s)
        policy = prepo.create(tenant_id=_TENANT, policy_number=f"POL-{uuid.uuid4().hex[:6]}",
                              policy_type=InsurancePolicyType.CARGO, status=InsurancePolicyStatus.ACTIVE)
        s.commit()
        crepo = ClaimRepository(s)
        sid, eid = uuid.uuid4(), uuid.uuid4()
        claim = crepo.create(tenant_id=_TENANT, claim_number="CLM-FIND", claim_type=ClaimType.SHIPMENT_LOSS,
                             status=ClaimStatus.CREATED, policy_id=policy.id, shipment_id=sid, equipment_id=eid)
        s.commit()
        assert crepo.get_by_number("CLM-FIND") is not None
        assert crepo.get_active_policy_for_claim(claim) is not None
        assert len(crepo.list_claims_for_shipment(sid)) == 1
        assert len(crepo.list_claims_for_equipment(eid)) == 1
        items, total = crepo.list_claims(status=ClaimStatus.CREATED, limit=1)
        assert total >= 1
    finally:
        s.close()


def test_damage_and_liability_for_claim(Session):
    s = Session()
    try:
        crepo = ClaimRepository(s)
        claim = crepo.create(tenant_id=_TENANT, claim_number=f"CLM-{uuid.uuid4().hex[:6]}",
                             claim_type=ClaimType.SHIPMENT_DAMAGE, status=ClaimStatus.CREATED)
        s.commit()
        drepo = DamageReportRepository(s)
        drepo.create(tenant_id=_TENANT, claim_id=claim.id, damage_type="cargo_damage", severity="high")
        s.commit()
        assert len(drepo.list_damage_reports_for_claim(claim.id)) == 1

        lrepo = LiabilityRecordRepository(s)
        lrepo.create(tenant_id=_TENANT, claim_id=claim.id, responsible_party_type="carrier", liability_percentage=40)
        lrepo.create(tenant_id=_TENANT, claim_id=claim.id, responsible_party_type="driver", liability_percentage=25)
        s.commit()
        assert len(lrepo.list_liability_records_for_claim(claim.id)) == 2
        assert lrepo.total_liability_percentage(claim.id) == 65.0
    finally:
        s.close()
