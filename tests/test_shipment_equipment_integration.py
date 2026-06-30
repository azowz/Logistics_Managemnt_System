"""Integration: Shipment validates a referenced Equipment unit (Sprint 6).

Exercises ShipmentService.create_shipment / update_shipment with ``equipment_id``
against a real (SQLite) schema containing both domains. EventStore is patched.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import ShipmentStatus
from app.services.exceptions import ConflictError, ValidationError
from app.services.shipment_service import ShipmentService
from shipment_sqlite import make_engine, seed_equipment, seed_prereqs

_TENANT = uuid.uuid4()
_CLIENT = uuid.uuid4()
_ORIGIN = uuid.uuid4()
_DEST = uuid.uuid4()
_CAT = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_prereqs(
        SessionLocal,
        tenant_id=_TENANT,
        client_id=_CLIENT,
        origin_id=_ORIGIN,
        dest_id=_DEST,
    )
    return SessionLocal


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.shipment_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.shipment_service.get_current_user_id", return_value=None),
        patch("app.services.shipment_service.EventStoreRepository", autospec=True) as M,
    ):
        inst = M.return_value
        inst.next_aggregate_version.return_value = 1
        inst.append.return_value = None
        yield


def _seed_eq(Session, *, status="active", weight=None, volume=None):
    eid = uuid.uuid4()
    seed_equipment(
        Session,
        tenant_id=_TENANT,
        category_id=_CAT,
        equipment_id=eid,
        status=status,
        weight_kg=weight,
        volume_m3=volume,
    )
    return eid


def _create_kwargs(**ov):
    base = dict(
        client_id=_CLIENT,
        origin_warehouse_id=_ORIGIN,
        destination_warehouse_id=_DEST,
        weight_kg=10000,
        volume_m3=50,
    )
    base.update(ov)
    return base


def test_create_shipment_with_valid_equipment(Session):
    s = Session()
    try:
        eq = _seed_eq(Session, weight=8000, volume=30)
        svc = ShipmentService(s)
        shipment = svc.create_shipment(
            reference_code=f"SHP-EQ-{uuid.uuid4().hex[:6]}",
            equipment_id=eq,
            **_create_kwargs(),
        )
        assert shipment.equipment_id == eq
        assert shipment.status == ShipmentStatus.CREATED
    finally:
        s.close()


def test_create_shipment_cross_tenant_equipment_rejected(Session):
    s = Session()
    try:
        # Equipment seeded under a different tenant.
        other_tenant = uuid.uuid4()
        other_cat = uuid.uuid4()
        eid = uuid.uuid4()
        # Seed a tenant row for the foreign tenant so FK holds.
        from app.models.tenant import Tenant

        s2 = Session()
        if s2.get(Tenant, other_tenant) is None:
            s2.add(Tenant(id=other_tenant, slug=f"o-{other_tenant.hex[:6]}", name="Other", status="active", isolation_mode="shared"))
            s2.commit()
        s2.close()
        seed_equipment(Session, tenant_id=other_tenant, category_id=other_cat, equipment_id=eid)

        svc = ShipmentService(s)
        with pytest.raises(ValidationError, match="Equipment"):
            svc.create_shipment(
                reference_code=f"SHP-XT-{uuid.uuid4().hex[:6]}",
                equipment_id=eid,
                **_create_kwargs(),
            )
    finally:
        s.close()


def test_create_shipment_decommissioned_equipment_rejected(Session):
    s = Session()
    try:
        eq = _seed_eq(Session, status="decommissioned")
        svc = ShipmentService(s)
        with pytest.raises(ValidationError, match="decommissioned"):
            svc.create_shipment(
                reference_code=f"SHP-DC-{uuid.uuid4().hex[:6]}",
                equipment_id=eq,
                **_create_kwargs(),
            )
    finally:
        s.close()


def test_create_shipment_non_assignable_equipment_rejected(Session):
    s = Session()
    try:
        eq = _seed_eq(Session, status="under_maintenance")
        svc = ShipmentService(s)
        with pytest.raises(ConflictError, match="cannot be assigned"):
            svc.create_shipment(
                reference_code=f"SHP-UM-{uuid.uuid4().hex[:6]}",
                equipment_id=eq,
                **_create_kwargs(),
            )
    finally:
        s.close()


def test_create_shipment_equipment_exclusivity(Session):
    s = Session()
    try:
        eq = _seed_eq(Session)
        svc = ShipmentService(s)
        first = svc.create_shipment(
            reference_code=f"SHP-EX1-{uuid.uuid4().hex[:6]}",
            equipment_id=eq,
            **_create_kwargs(),
        )
        # Move first shipment into an active-assignment state.
        svc.mark_ready(first.id)
        # A second active shipment cannot reuse the same equipment.
        with pytest.raises(ConflictError, match="already assigned"):
            svc.create_shipment(
                reference_code=f"SHP-EX2-{uuid.uuid4().hex[:6]}",
                equipment_id=eq,
                **_create_kwargs(),
            )
    finally:
        s.close()


def test_create_shipment_weight_incompatible_rejected(Session):
    s = Session()
    try:
        eq = _seed_eq(Session, weight=20000)  # heavier than shipment weight
        svc = ShipmentService(s)
        with pytest.raises(ValidationError, match="weight"):
            svc.create_shipment(
                reference_code=f"SHP-W-{uuid.uuid4().hex[:6]}",
                equipment_id=eq,
                **_create_kwargs(weight_kg=10000),
            )
    finally:
        s.close()


def test_shipment_without_equipment_still_works(Session):
    s = Session()
    try:
        svc = ShipmentService(s)
        shipment = svc.create_shipment(
            reference_code=f"SHP-NOEQ-{uuid.uuid4().hex[:6]}",
            **_create_kwargs(),
        )
        assert shipment.equipment_id is None
    finally:
        s.close()
