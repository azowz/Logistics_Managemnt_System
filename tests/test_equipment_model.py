"""ORM-level tests for the Equipment model (defaults, constraints, soft-delete)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.enums import (
    EquipmentAvailability,
    EquipmentOwnershipType,
    EquipmentStatus,
)
from app.models.equipment import Equipment
from equipment_sqlite import make_engine, seed_prereqs

_TENANT = uuid.uuid4()
_CAT = uuid.uuid4()
_MODEL = uuid.uuid4()
_WH = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_prereqs(
        SessionLocal, tenant_id=_TENANT, category_id=_CAT, model_id=_MODEL, warehouse_id=_WH
    )
    return SessionLocal


def _new(**ov) -> Equipment:
    data = dict(
        tenant_id=_TENANT,
        equipment_code=f"EQP-{uuid.uuid4().hex[:8]}",
        asset_tag=f"TAG-{uuid.uuid4().hex[:8]}",
        category_id=_CAT,
        name="Excavator",
    )
    data.update(ov)
    return Equipment(**data)


def test_defaults(Session):
    s = Session()
    try:
        eq = _new()
        s.add(eq)
        s.commit()
        s.refresh(eq)
        assert eq.status == EquipmentStatus.ACTIVE
        assert eq.availability_status == EquipmentAvailability.AVAILABLE
        assert eq.ownership_type == EquipmentOwnershipType.OWNED
        assert eq.version == 1
        assert eq.requires_permit is False
        assert eq.is_deleted is False
    finally:
        s.close()


def test_tags_jsonb(Session):
    s = Session()
    try:
        eq = _new(tags=["oversize", "crane"])
        s.add(eq)
        s.commit()
        s.refresh(eq)
        assert eq.tags == ["oversize", "crane"]
    finally:
        s.close()


def test_unique_code_per_tenant(Session):
    s = Session()
    try:
        code = f"EQP-DUP-{uuid.uuid4().hex[:6]}"
        s.add(_new(equipment_code=code))
        s.commit()
        s.add(_new(equipment_code=code))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()


def test_unique_asset_tag_per_tenant(Session):
    s = Session()
    try:
        tag = f"TAG-DUP-{uuid.uuid4().hex[:6]}"
        s.add(_new(asset_tag=tag))
        s.commit()
        s.add(_new(asset_tag=tag))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()


def test_negative_weight_rejected(Session):
    s = Session()
    try:
        s.add(_new(weight_kg=-5))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()


def test_soft_delete_restore(Session):
    s = Session()
    try:
        eq = _new()
        s.add(eq)
        s.commit()
        eq.soft_delete()
        eq.deleted_by = uuid.uuid4()
        s.commit()
        s.refresh(eq)
        assert eq.is_deleted is True
        eq.restore()
        eq.deleted_by = None
        s.commit()
        s.refresh(eq)
        assert eq.is_deleted is False
    finally:
        s.close()


def test_version_increments(Session):
    s = Session()
    try:
        eq = _new()
        s.add(eq)
        s.commit()
        assert eq.version == 1
        eq.notes = "serviced"
        s.commit()
        s.refresh(eq)
        assert eq.version == 2
    finally:
        s.close()


def test_warehouse_and_model_optional(Session):
    s = Session()
    try:
        eq = _new(model_id=_MODEL, current_warehouse_id=_WH, current_location="Yard A")
        s.add(eq)
        s.commit()
        s.refresh(eq)
        assert eq.model_id == _MODEL
        assert eq.current_warehouse_id == _WH
    finally:
        s.close()
