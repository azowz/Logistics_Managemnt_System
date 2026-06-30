"""Tests for the ComplianceValidationService dispatch gate (SQLite)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.common.datetime import utcnow
from app.models.compliance import ComplianceCheck, Escort, Permit
from app.models.shipment import Shipment
from app.services.compliance_service import ComplianceValidationService
from compliance_sqlite import make_engine, seed_shipment_with_equipment, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def _gate(s, shipment_id):
    shipment = s.get(Shipment, shipment_id)
    return ComplianceValidationService(s).validate_dispatch(shipment=shipment, stage="assign")


def _make_shipment(Session, **flags):
    cat, eq, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seed_shipment_with_equipment(
        Session, tenant_id=_TENANT, client_user_id=_USER, category_id=cat,
        equipment_id=eq, shipment_id=sid, **flags,
    )
    return sid, eq


def _active_permit(s, shipment_id, *, valid_until=None):
    p = Permit(tenant_id=_TENANT, permit_number=f"PMT-{uuid.uuid4().hex[:8]}",
               permit_type="oversize", status="active", shipment_id=shipment_id,
               valid_from=utcnow() - timedelta(days=30), valid_until=valid_until)
    s.add(p)
    s.commit()
    return p


def test_no_equipment_allowed(Session):
    s = Session()
    try:
        sid = uuid.uuid4()
        # A shipment with no equipment_id.
        from app.models.warehouse import Warehouse
        wid = uuid.uuid4()
        s.add(Warehouse(id=wid, tenant_id=_TENANT, code=f"W{wid.hex[:6]}", name="d",
                        address_line1="1", city="R", country="SA",
                        capacity_weight_kg=1e6, capacity_volume_m3=1e6))
        s.commit()
        s.add(Shipment(id=sid, tenant_id=_TENANT, reference_code=f"S{sid.hex[:6]}",
                       client_id=_USER, origin_warehouse_id=wid, destination_warehouse_id=wid,
                       status="ready", weight_kg=100, volume_m3=2))
        s.commit()
        assert _gate(s, sid).allowed is True
    finally:
        s.close()


def test_permit_required_no_permit_blocked(Session):
    s = Session()
    try:
        sid, _ = _make_shipment(Session, requires_permit=True)
        result = _gate(s, sid)
        assert result.allowed is False
        assert any("permit" in r.lower() for r in result.blocking_reasons)
        assert "movement_permit" in result.required_permits
    finally:
        s.close()


def test_permit_required_with_active_permit_allowed(Session):
    s = Session()
    try:
        sid, _ = _make_shipment(Session, requires_permit=True)
        _active_permit(s, sid, valid_until=utcnow() + timedelta(days=5))
        assert _gate(s, sid).allowed is True
    finally:
        s.close()


def test_expired_permit_window_blocked(Session):
    s = Session()
    try:
        sid, _ = _make_shipment(Session, requires_permit=True)
        _active_permit(s, sid, valid_until=utcnow() - timedelta(days=1))
        result = _gate(s, sid)
        assert result.allowed is False
        assert any("expired" in r.lower() for r in result.blocking_reasons)
    finally:
        s.close()


def test_escort_required_no_escort_blocked(Session):
    s = Session()
    try:
        # requires_escort but not requires_permit
        sid, _ = _make_shipment(Session, requires_escort=True)
        result = _gate(s, sid)
        assert result.allowed is False
        assert any("escort" in r.lower() for r in result.blocking_reasons)
    finally:
        s.close()


def test_escort_required_with_escort_allowed(Session):
    s = Session()
    try:
        sid, _ = _make_shipment(Session, requires_escort=True)
        s.add(Escort(tenant_id=_TENANT, shipment_id=sid, escort_type="police_escort", status="scheduled"))
        s.commit()
        assert _gate(s, sid).allowed is True
    finally:
        s.close()


def test_failed_blocking_check_blocks(Session):
    s = Session()
    try:
        sid, eq = _make_shipment(Session)  # no flags → no live permit requirement
        s.add(ComplianceCheck(tenant_id=_TENANT, shipment_id=sid, check_type="route_restriction",
                              status="failed", blocking=True, failure_reasons=["bridge limit"]))
        s.commit()
        result = _gate(s, sid)
        assert result.allowed is False
        assert result.compliance_check_ids
    finally:
        s.close()


def test_hazardous_requires_permit(Session):
    s = Session()
    try:
        sid, _ = _make_shipment(Session, hazardous=True)
        # hazardous ⇒ needs permit; none present ⇒ blocked
        assert _gate(s, sid).allowed is False
    finally:
        s.close()
