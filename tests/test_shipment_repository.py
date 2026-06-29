"""Tests for ShipmentRepository: no-commit contract, queries, filters, soft-delete."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import ShipmentPriority, ShipmentStatus
from app.repositories.errors import NotFoundError
from app.repositories.shipment_repository import ShipmentRepository
from shipment_sqlite import make_engine, seed_driver_and_vehicle, seed_prereqs

_TENANT = uuid.uuid4()
_CLIENT = uuid.uuid4()
_ORIGIN = uuid.uuid4()
_DEST = uuid.uuid4()
_DRV_USER = uuid.uuid4()
_DRIVER = uuid.uuid4()
_VEHICLE = uuid.uuid4()


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
    seed_driver_and_vehicle(
        SessionLocal,
        tenant_id=_TENANT,
        driver_user_id=_DRV_USER,
        driver_id=_DRIVER,
        vehicle_id=_VEHICLE,
    )
    return SessionLocal


def _create(repo, session, *, status=ShipmentStatus.CREATED, **overrides):
    data = dict(
        tenant_id=_TENANT,
        reference_code=f"SHP-{uuid.uuid4().hex[:8]}",
        client_id=_CLIENT,
        origin_warehouse_id=_ORIGIN,
        destination_warehouse_id=_DEST,
        weight_kg=5,
        volume_m3=1,
        status=status,
    )
    data.update(overrides)
    shipment = repo.create(**data)
    session.commit()
    session.refresh(shipment)
    return shipment


def test_create_does_not_commit(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        shipment = repo.create(
            tenant_id=_TENANT,
            reference_code=f"SHP-NC-{uuid.uuid4().hex[:6]}",
            client_id=_CLIENT,
            origin_warehouse_id=_ORIGIN,
            destination_warehouse_id=_DEST,
            weight_kg=5,
            volume_m3=1,
        )
        sid = shipment.id
        # Repository must NOT have committed — a rollback discards the row.
        s.rollback()
        assert repo.get_by_id(sid) is None
    finally:
        s.close()


def test_update_does_not_commit(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        shipment = _create(repo, s)
        repo.update(shipment, cargo_type="glass")
        s.rollback()
        s.refresh(shipment)
        assert shipment.cargo_type != "glass"
    finally:
        s.close()


def test_get_by_id_variants(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        shipment = _create(repo, s)
        assert repo.get_by_id(shipment.id).id == shipment.id
        assert repo.get_by_id(str(shipment.id)).id == shipment.id
        assert repo.get_by_id("not-a-uuid") is None
        assert repo.get_by_id(uuid.uuid4()) is None
    finally:
        s.close()


def test_get_by_id_or_raise(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        with pytest.raises(NotFoundError):
            repo.get_by_id_or_raise(uuid.uuid4())
    finally:
        s.close()


def test_get_by_reference_code_filters_deleted(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        ref = f"SHP-REF-{uuid.uuid4().hex[:6]}"
        shipment = _create(repo, s, reference_code=ref)
        assert repo.get_by_reference_code(ref).id == shipment.id
        repo.soft_delete(shipment, deleted_by=None)
        s.commit()
        assert repo.get_by_reference_code(ref) is None  # soft-deleted hidden
        assert repo.get_by_reference(ref).id == shipment.id  # legacy sees it
    finally:
        s.close()


def test_list_shipments_filters_and_total(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        _create(repo, s, status=ShipmentStatus.READY, priority=ShipmentPriority.HIGH)
        _create(repo, s, status=ShipmentStatus.READY, priority=ShipmentPriority.LOW)
        items, total = repo.list_shipments(status=ShipmentStatus.READY, limit=1)
        assert total >= 2
        assert len(items) == 1  # limit honoured, total ignores limit
        high, total_high = repo.list_shipments(priority=ShipmentPriority.HIGH)
        assert all(i.priority == ShipmentPriority.HIGH for i in high)
    finally:
        s.close()


def test_list_shipments_search_and_sort(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        _create(repo, s, cargo_type="refrigerated pharma")
        items, _ = repo.list_shipments(q="pharma")
        assert any("pharma" in (i.cargo_type or "") for i in items)
        asc_items, _ = repo.list_shipments(sort_by="reference_code", sort_dir="asc")
        refs = [i.reference_code for i in asc_items]
        assert refs == sorted(refs)
    finally:
        s.close()


def test_list_excludes_soft_deleted_by_default(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        shipment = _create(repo, s)
        repo.soft_delete(shipment, deleted_by=None)
        s.commit()
        active, _ = repo.list_shipments(include_deleted=False)
        assert shipment.id not in {i.id for i in active}
        withdel, _ = repo.list_shipments(include_deleted=True)
        assert shipment.id in {i.id for i in withdel}
    finally:
        s.close()


def test_active_assignment_queries(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        active = _create(
            repo, s, status=ShipmentStatus.IN_TRANSIT, driver_id=_DRIVER, vehicle_id=_VEHICLE
        )
        assert repo.has_active_driver_assignment(_DRIVER) is True
        assert repo.has_active_vehicle_assignment(_VEHICLE) is True
        # Excluding the only active shipment clears the conflict.
        assert (
            repo.has_active_driver_assignment(_DRIVER, exclude_shipment_id=active.id)
            is False
        )
        assert repo.has_active_driver_assignment(uuid.uuid4()) is False
    finally:
        s.close()


def test_restore(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        shipment = _create(repo, s)
        repo.soft_delete(shipment, deleted_by=_CLIENT)
        s.commit()
        repo.restore(shipment)
        s.commit()
        s.refresh(shipment)
        assert shipment.is_deleted is False
        assert shipment.deleted_by is None
    finally:
        s.close()


def test_legacy_list(Session):
    s = Session()
    try:
        repo = ShipmentRepository(s)
        _create(repo, s)
        rows = repo.list(offset=0, limit=5)
        assert isinstance(rows, list)
    finally:
        s.close()
