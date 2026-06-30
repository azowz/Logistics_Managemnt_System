"""Integration: Claims may use compliance checks / permits as evidence (SQLite)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import ClaimType
from app.services.claims_service import ClaimsService
from app.services.exceptions import ValidationError
from insurance_sqlite import (
    make_engine,
    seed_active_policy,
    seed_compliance_check,
    seed_tenant_user,
)

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


def test_compliance_violation_references_failed_check(Session):
    chk = uuid.uuid4()
    seed_compliance_check(Session, tenant_id=_TENANT, check_id=chk, status="failed")
    s = Session()
    try:
        claim = ClaimsService(s).create_claim(claim_type=ClaimType.COMPLIANCE_VIOLATION,
                                              compliance_check_id=chk, policy_id=_POLICY)
        assert claim.compliance_check_id == chk
    finally:
        s.close()


def test_cross_tenant_compliance_check_rejected(Session):
    other = uuid.uuid4()
    from app.models.tenant import Tenant
    s0 = Session()
    s0.add(Tenant(id=other, slug=f"o{other.hex[:6]}", name="O", status="active", isolation_mode="shared"))
    s0.commit(); s0.close()
    chk = uuid.uuid4()
    seed_compliance_check(Session, tenant_id=other, check_id=chk, status="failed")
    s = Session()
    try:
        with pytest.raises(ValidationError, match="Compliance check"):
            ClaimsService(s).create_claim(claim_type=ClaimType.COMPLIANCE_VIOLATION, compliance_check_id=chk)
    finally:
        s.close()
