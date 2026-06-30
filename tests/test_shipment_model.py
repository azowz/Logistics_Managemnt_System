"""ORM-level tests for the Shipment model (defaults, constraints, soft-delete)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.enums import ShipmentPriority, ShipmentStatus
from app.models.shipment import Shipment
from shipment_sqlite import make_engine, seed_prereqs

_TENANT = uuid.uuid4()
_CLIENT = uuid.uuid4()
_ORIGIN = uuid.uuid4()
_DEST = uuid.uuid4()


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


def _new_shipment(**overrides) -> Shipment:
    data = dict(
        tenant_id=_TENANT,
        reference_code=f"SHP-{uuid.uuid4().hex[:8]}",
        client_id=_CLIENT,
        origin_warehouse_id=_ORIGIN,
        destination_warehouse_id=_DEST,
        weight_kg=10,
        volume_m3=2,
    )
    data.update(overrides)
    return Shipment(**data)


def test_defaults(Session):
    s = Session()
    try:
        shipment = _new_shipment()
        s.add(shipment)
        s.commit()
        s.refresh(shipment)
        assert shipment.id is not None
        assert shipment.status == ShipmentStatus.CREATED
        assert shipment.priority == ShipmentPriority.NORMAL
        assert shipment.version == 1
        assert shipment.currency_code == "SAR"
        assert shipment.created_at is not None
        assert shipment.deleted_at is None
        assert shipment.is_deleted is False
    finally:
        s.close()


def test_new_lifecycle_columns_exist(Session):
    s = Session()
    try:
        shipment = _new_shipment(cargo_description="pallets", return_reason=None)
        s.add(shipment)
        s.commit()
        s.refresh(shipment)
        # New Sprint-5 columns are addressable.
        for col in (
            "order_id",
            "equipment_id",
            "picked_up_at",
            "failed_at",
            "return_reason",
            "deleted_by",
        ):
            assert hasattr(shipment, col)
        assert shipment.cargo_description == "pallets"
    finally:
        s.close()


def test_weight_must_be_positive(Session):
    s = Session()
    try:
        s.add(_new_shipment(weight_kg=0))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()


def test_volume_must_be_positive(Session):
    s = Session()
    try:
        s.add(_new_shipment(volume_m3=0))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()


def test_reference_code_unique_per_tenant(Session):
    s = Session()
    try:
        ref = f"SHP-DUP-{uuid.uuid4().hex[:6]}"
        s.add(_new_shipment(reference_code=ref))
        s.commit()
        s.add(_new_shipment(reference_code=ref))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()


def test_soft_delete_and_restore(Session):
    s = Session()
    try:
        shipment = _new_shipment()
        s.add(shipment)
        s.commit()

        shipment.soft_delete()
        shipment.deleted_by = _CLIENT
        s.commit()
        s.refresh(shipment)
        assert shipment.is_deleted is True
        assert shipment.deleted_at is not None

        shipment.restore()
        shipment.deleted_by = None
        s.commit()
        s.refresh(shipment)
        assert shipment.is_deleted is False
    finally:
        s.close()


def test_priority_persists(Session):
    s = Session()
    try:
        shipment = _new_shipment(priority=ShipmentPriority.URGENT)
        s.add(shipment)
        s.commit()
        s.refresh(shipment)
        assert shipment.priority == ShipmentPriority.URGENT
    finally:
        s.close()


def test_version_increments_on_update(Session):
    s = Session()
    try:
        shipment = _new_shipment()
        s.add(shipment)
        s.commit()
        assert shipment.version == 1
        shipment.cargo_type = "fragile"
        s.commit()
        s.refresh(shipment)
        assert shipment.version == 2
    finally:
        s.close()
