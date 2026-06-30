"""Tests for compliance repositories: no-commit, query helpers, soft-delete."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import ComplianceCheckStatus, ComplianceCheckType, PermitStatus, PermitType
from app.repositories.compliance_repository import (
    AxleWeightProfileRepository,
    ComplianceCheckRepository,
    EscortRepository,
    OperatorCertificationRepository,
    PermitRepository,
    RouteRestrictionRepository,
)
from app.repositories.errors import NotFoundError
from compliance_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()
_SHIP = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def test_permit_create_no_commit_and_lookups(Session):
    s = Session()
    try:
        repo = PermitRepository(s)
        p = repo.create(tenant_id=_TENANT, permit_number="PMT-NC", permit_type=PermitType.OVERSIZE,
                        status=PermitStatus.ACTIVE, shipment_id=_SHIP)
        pid = p.id
        s.rollback()
        assert repo.get_by_id(pid) is None  # not committed
    finally:
        s.close()


def test_permit_active_for_shipment(Session):
    s = Session()
    try:
        repo = PermitRepository(s)
        repo.create(tenant_id=_TENANT, permit_number=f"PMT-{uuid.uuid4().hex[:6]}",
                    permit_type=PermitType.OVERSIZE, status=PermitStatus.ACTIVE, shipment_id=_SHIP)
        s.commit()
        assert repo.get_active_permit_for_shipment(_SHIP) is not None
        assert repo.get_active_permit_for_shipment(uuid.uuid4()) is None
        with pytest.raises(NotFoundError):
            repo.get_by_id_or_raise(uuid.uuid4())
    finally:
        s.close()


def test_permit_list_filters(Session):
    s = Session()
    try:
        repo = PermitRepository(s)
        repo.create(tenant_id=_TENANT, permit_number=f"PMT-{uuid.uuid4().hex[:6]}",
                    permit_type=PermitType.OVERWEIGHT, status=PermitStatus.DRAFT)
        s.commit()
        items, total = repo.list_permits(status=PermitStatus.DRAFT, limit=1)
        assert total >= 1 and len(items) == 1
    finally:
        s.close()


def test_escort_active_for_shipment(Session):
    s = Session()
    try:
        repo = EscortRepository(s)
        repo.create(tenant_id=_TENANT, shipment_id=_SHIP, escort_type="police_escort", status="scheduled")
        s.commit()
        assert len(repo.get_active_escorts_for_shipment(_SHIP)) >= 1
    finally:
        s.close()


def test_failed_blocking_checks(Session):
    s = Session()
    try:
        repo = ComplianceCheckRepository(s)
        repo.create(tenant_id=_TENANT, shipment_id=_SHIP, check_type=ComplianceCheckType.PERMIT_REQUIRED,
                    status=ComplianceCheckStatus.FAILED, blocking=True)
        repo.create(tenant_id=_TENANT, shipment_id=_SHIP, check_type=ComplianceCheckType.OVERSIZE,
                    status=ComplianceCheckStatus.PASSED, blocking=True)
        s.commit()
        failed = repo.list_failed_blocking_checks(_SHIP)
        assert len(failed) == 1
        assert failed[0].check_type == ComplianceCheckType.PERMIT_REQUIRED
    finally:
        s.close()


def test_list_methods_and_soft_delete(Session):
    s = Session()
    try:
        # escorts list + soft delete
        er = EscortRepository(s)
        e = er.create(tenant_id=_TENANT, shipment_id=uuid.uuid4(), escort_type="pilot_vehicle", status="planned")
        s.commit()
        items, total = er.list_escorts(status=None)
        assert total >= 1
        er.soft_delete(e, deleted_by=_USER)
        s.commit()
        er.restore(e)
        s.commit()

        # axle profiles list
        ar = AxleWeightProfileRepository(s)
        ar.create(tenant_id=_TENANT, axle_count=2, total_weight=15000, is_compliant=True)
        s.commit()
        _, atot = ar.list_profiles()
        assert atot >= 1

        # checks list (status filter)
        cr = ComplianceCheckRepository(s)
        cr.create(tenant_id=_TENANT, shipment_id=uuid.uuid4(),
                  check_type=ComplianceCheckType.OVERSIZE, status=ComplianceCheckStatus.WARNING, blocking=False)
        s.commit()
        _, ctot = cr.list_checks(status=ComplianceCheckStatus.WARNING)
        assert ctot >= 1

        # certifications list
        ocr = OperatorCertificationRepository(s)
        ocr.create(tenant_id=_TENANT, user_id=_USER, certification_type="hazmat", status="active")
        s.commit()
        _, otot = ocr.list_certifications(user_id=_USER)
        assert otot >= 1

        # permit search by q
        pr = PermitRepository(s)
        pr.create(tenant_id=_TENANT, permit_number="PMT-FINDME", permit_type=PermitType.GOVERNMENT,
                  status=PermitStatus.DRAFT, issuing_authority="RGA")
        s.commit()
        found, _ = pr.list_permits(q="FINDME")
        assert any(p.permit_number == "PMT-FINDME" for p in found)

        # route restriction list
        rr = RouteRestrictionRepository(s)
        rr.create(tenant_id=_TENANT, restriction_type="road_closure", region="Dammam")
        s.commit()
        _, rtot = rr.list_restrictions(region="Dammam")
        assert rtot >= 1
    finally:
        s.close()


def test_route_restrictions_and_cert(Session):
    s = Session()
    try:
        rr = RouteRestrictionRepository(s)
        rr.create(tenant_id=_TENANT, restriction_type="height_limit", region="Makkah", active=True)
        s.commit()
        assert len(rr.get_route_restrictions(region="Makkah")) >= 1
        assert rr.get_route_restrictions(region="NOWHERE") == []

        cr = OperatorCertificationRepository(s)
        cr.create(tenant_id=_TENANT, user_id=_USER, certification_type="crane", status="active")
        s.commit()
        assert cr.get_valid_operator_certification(_USER, certification_type="crane") is not None
        assert cr.get_valid_operator_certification(_USER, certification_type="missing") is None
    finally:
        s.close()
