"""ORM-level tests for compliance models (defaults, constraints, soft-delete)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.compliance import OperatorCertification, Permit, RouteRestriction
from app.models.enums import PermitStatus, PermitType
from compliance_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def _permit(**ov) -> Permit:
    data = dict(tenant_id=_TENANT, permit_number=f"PMT-{uuid.uuid4().hex[:8]}",
                permit_type=PermitType.OVERSIZE)
    data.update(ov)
    return Permit(**data)


def test_permit_defaults(Session):
    s = Session()
    try:
        p = _permit()
        s.add(p)
        s.commit()
        s.refresh(p)
        assert p.status == PermitStatus.DRAFT
        assert p.version == 1
        assert p.requires_escort is False
        assert p.is_deleted is False
    finally:
        s.close()


def test_permit_number_unique_per_tenant(Session):
    s = Session()
    try:
        num = f"PMT-DUP-{uuid.uuid4().hex[:6]}"
        s.add(_permit(permit_number=num))
        s.commit()
        s.add(_permit(permit_number=num))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()


def test_permit_conditions_jsonb(Session):
    s = Session()
    try:
        p = _permit(conditions={"time_window": "night", "escort": True})
        s.add(p)
        s.commit()
        s.refresh(p)
        assert p.conditions["time_window"] == "night"
    finally:
        s.close()


def test_permit_soft_delete_restore(Session):
    s = Session()
    try:
        p = _permit()
        s.add(p)
        s.commit()
        p.soft_delete()
        p.deleted_by = _USER
        s.commit()
        s.refresh(p)
        assert p.is_deleted
        p.restore()
        p.deleted_by = None
        s.commit()
        s.refresh(p)
        assert not p.is_deleted
    finally:
        s.close()


def test_route_restriction_defaults(Session):
    s = Session()
    try:
        r = RouteRestriction(tenant_id=_TENANT, restriction_type="height_limit", region="Riyadh")
        s.add(r)
        s.commit()
        s.refresh(r)
        assert r.active is True
        assert r.version == 1
    finally:
        s.close()


def test_operator_certification_defaults(Session):
    s = Session()
    try:
        c = OperatorCertification(tenant_id=_TENANT, user_id=_USER, certification_type="crane")
        s.add(c)
        s.commit()
        s.refresh(c)
        assert c.status.value == "active"
        assert c.version == 1
    finally:
        s.close()


def test_permit_version_increments(Session):
    s = Session()
    try:
        p = _permit()
        s.add(p)
        s.commit()
        assert p.version == 1
        p.notes = "x"
        s.commit()
        s.refresh(p)
        assert p.version == 2
    finally:
        s.close()
