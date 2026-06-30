"""Integration: Shipment dispatch is gated by Compliance (SQLite).

Proves the dispatch gate: normal shipments pass; permit/escort-required cargo is
blocked without the prerequisite and allowed once it is satisfied.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.common.datetime import utcnow
from app.models.compliance import Escort, Permit
from app.models.driver import Driver
from app.models.shipment import Shipment
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.exceptions import ConflictError
from app.services.shipment_service import ShipmentService
from compliance_sqlite import make_engine, seed_shipment_with_equipment, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.shipment_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.shipment_service.get_current_user_id", return_value=_USER),
        patch("app.services.shipment_service.EventStoreRepository", autospec=True) as M,
    ):
        inst = M.return_value
        inst.next_aggregate_version.return_value = 1
        inst.append.return_value = None
        yield


def _driver_vehicle(Session):
    """Seed an available driver (driver-role user) + active vehicle; return ids."""
    s = Session()
    try:
        du, did, vid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        s.add(User(id=du, tenant_id=_TENANT, email=f"d{du.hex[:8]}@t.test",
                   hashed_password="x", role="driver", is_active=True))
        s.commit()
        s.add(Driver(id=did, tenant_id=_TENANT, user_id=du, license_number=f"L{did.hex[:6]}", is_available=True))
        s.add(Vehicle(id=vid, tenant_id=_TENANT, plate_number=f"P{vid.hex[:6]}", status="active",
                      capacity_weight_kg=1_000_000, capacity_volume_m3=1_000_000))
        s.commit()
        return did, vid
    finally:
        s.close()


def _shipment(Session, **flags):
    cat, eq, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seed_shipment_with_equipment(Session, tenant_id=_TENANT, client_user_id=_USER,
                                 category_id=cat, equipment_id=eq, shipment_id=sid, **flags)
    return sid


def _assign(Session, sid):
    did, vid = _driver_vehicle(Session)
    s = Session()
    try:
        return ShipmentService(s).assign_shipment(sid, driver_id=did, vehicle_id=vid)
    finally:
        s.close()


def test_normal_shipment_no_equipment_assigns(Session):
    # Shipment WITHOUT equipment passes the gate.
    from app.models.warehouse import Warehouse
    s = Session()
    try:
        wid, sid = uuid.uuid4(), uuid.uuid4()
        s.add(Warehouse(id=wid, tenant_id=_TENANT, code=f"W{wid.hex[:6]}", name="d",
                        address_line1="1", city="R", country="SA",
                        capacity_weight_kg=1e6, capacity_volume_m3=1e6))
        s.commit()
        s.add(Shipment(id=sid, tenant_id=_TENANT, reference_code=f"S{sid.hex[:6]}",
                       client_id=_USER, origin_warehouse_id=wid, destination_warehouse_id=wid,
                       status="ready", weight_kg=100, volume_m3=2))
        s.commit()
    finally:
        s.close()
    result = _assign(Session, sid)
    assert result.status.value == "assigned"


def test_permit_required_blocks_assign(Session):
    sid = _shipment(Session, requires_permit=True)
    with pytest.raises(ConflictError, match="compliance"):
        _assign(Session, sid)


def test_active_permit_allows_assign(Session):
    sid = _shipment(Session, requires_permit=True)
    s = Session()
    try:
        s.add(Permit(tenant_id=_TENANT, permit_number=f"PMT-{uuid.uuid4().hex[:8]}",
                     permit_type="oversize", status="active", shipment_id=sid,
                     valid_from=utcnow() - timedelta(days=1), valid_until=utcnow() + timedelta(days=5)))
        s.commit()
    finally:
        s.close()
    assert _assign(Session, sid).status.value == "assigned"


def test_expired_permit_blocks_assign(Session):
    sid = _shipment(Session, requires_permit=True)
    s = Session()
    try:
        s.add(Permit(tenant_id=_TENANT, permit_number=f"PMT-{uuid.uuid4().hex[:8]}",
                     permit_type="oversize", status="active", shipment_id=sid,
                     valid_from=utcnow() - timedelta(days=30), valid_until=utcnow() - timedelta(days=1)))
        s.commit()
    finally:
        s.close()
    with pytest.raises(ConflictError):
        _assign(Session, sid)


def test_escort_required_blocks_then_allows(Session):
    sid = _shipment(Session, requires_escort=True)
    with pytest.raises(ConflictError):
        _assign(Session, sid)
    # Add a scheduled escort → now allowed.
    s = Session()
    try:
        s.add(Escort(tenant_id=_TENANT, shipment_id=sid, escort_type="police_escort", status="scheduled"))
        s.commit()
    finally:
        s.close()
    assert _assign(Session, sid).status.value == "assigned"
