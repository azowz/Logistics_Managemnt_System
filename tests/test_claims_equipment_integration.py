"""Integration: Claims may reference equipment (SQLite)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import ClaimType
from app.services.claims_service import ClaimsService
from app.services.exceptions import ValidationError
from insurance_sqlite import make_engine, seed_active_policy, seed_equipment, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_POLICY = uuid.uuid4()
_CAT = uuid.uuid4()


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


def test_equipment_damage_claim_with_equipment(Session):
    eid = uuid.uuid4()
    seed_equipment(Session, tenant_id=_TENANT, category_id=_CAT, equipment_id=eid)
    s = Session()
    try:
        claim = ClaimsService(s).create_claim(claim_type=ClaimType.EQUIPMENT_DAMAGE, equipment_id=eid, policy_id=_POLICY)
        assert claim.equipment_id == eid
    finally:
        s.close()


def test_equipment_damage_requires_equipment_id(Session):
    s = Session()
    try:
        with pytest.raises(ValidationError, match="equipment_id"):
            ClaimsService(s).create_claim(claim_type=ClaimType.EQUIPMENT_DAMAGE, policy_id=_POLICY)
    finally:
        s.close()


def test_cross_tenant_equipment_rejected(Session):
    other = uuid.uuid4()
    from app.models.tenant import Tenant
    s0 = Session()
    s0.add(Tenant(id=other, slug=f"o{other.hex[:6]}", name="O", status="active", isolation_mode="shared"))
    s0.commit(); s0.close()
    eid = uuid.uuid4()
    seed_equipment(Session, tenant_id=other, category_id=uuid.uuid4(), equipment_id=eid)
    s = Session()
    try:
        with pytest.raises(ValidationError, match="Equipment"):
            ClaimsService(s).create_claim(claim_type=ClaimType.EQUIPMENT_DAMAGE, equipment_id=eid)
    finally:
        s.close()


def test_damage_report_references_equipment(Session):
    eid = uuid.uuid4()
    seed_equipment(Session, tenant_id=_TENANT, category_id=uuid.uuid4(), equipment_id=eid)
    s = Session()
    try:
        svc = ClaimsService(s)
        claim = svc.create_claim(claim_type=ClaimType.EQUIPMENT_DAMAGE, equipment_id=eid, policy_id=_POLICY)
        report = svc.create_damage_report(claim.id, damage_type="equipment_damage", severity="high", equipment_id=eid)
        assert report.equipment_id == eid
    finally:
        s.close()
