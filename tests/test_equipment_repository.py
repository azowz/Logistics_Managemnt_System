"""Tests for EquipmentRepository: no-commit contract, queries, filters, soft-delete."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import EquipmentAvailability, EquipmentStatus
from app.repositories.equipment_repository import (
    EquipmentCategoryRepository,
    EquipmentModelRepository,
    EquipmentRepository,
)
from app.repositories.errors import NotFoundError
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


def _create(repo, session, **ov):
    data = dict(
        tenant_id=_TENANT,
        equipment_code=f"EQP-{uuid.uuid4().hex[:8]}",
        asset_tag=f"TAG-{uuid.uuid4().hex[:8]}",
        category_id=_CAT,
        name="Excavator",
        status=EquipmentStatus.ACTIVE,
        availability_status=EquipmentAvailability.AVAILABLE,
    )
    data.update(ov)
    eq = repo.create(**data)
    session.commit()
    session.refresh(eq)
    return eq


def test_create_does_not_commit(Session):
    s = Session()
    try:
        repo = EquipmentRepository(s)
        eq = repo.create(
            tenant_id=_TENANT,
            equipment_code=f"EQP-NC-{uuid.uuid4().hex[:6]}",
            asset_tag=f"TAG-NC-{uuid.uuid4().hex[:6]}",
            category_id=_CAT,
            name="Loader",
        )
        eid = eq.id
        s.rollback()
        assert repo.get_by_id(eid) is None
    finally:
        s.close()


def test_get_by_id_variants(Session):
    s = Session()
    try:
        repo = EquipmentRepository(s)
        eq = _create(repo, s)
        assert repo.get_by_id(str(eq.id)).id == eq.id
        assert repo.get_by_id("bad") is None
        with pytest.raises(NotFoundError):
            repo.get_by_id_or_raise(uuid.uuid4())
    finally:
        s.close()


def test_get_by_code_asset_serial_filter_deleted(Session):
    s = Session()
    try:
        repo = EquipmentRepository(s)
        code = f"EQP-C-{uuid.uuid4().hex[:6]}"
        tag = f"TAG-C-{uuid.uuid4().hex[:6]}"
        eq = _create(repo, s, equipment_code=code, asset_tag=tag, serial_number="SER-1")
        assert repo.get_by_code(code).id == eq.id
        assert repo.get_by_asset_tag(tag).id == eq.id
        assert repo.get_by_serial_number("SER-1").id == eq.id
        repo.soft_delete(eq, deleted_by=None)
        s.commit()
        assert repo.get_by_code(code) is None
    finally:
        s.close()


def test_list_filters_and_total(Session):
    s = Session()
    try:
        repo = EquipmentRepository(s)
        _create(repo, s, availability_status=EquipmentAvailability.AVAILABLE)
        _create(repo, s, availability_status=EquipmentAvailability.AVAILABLE)
        items, total = repo.list_equipment(
            availability_status=EquipmentAvailability.AVAILABLE, limit=1
        )
        assert total >= 2 and len(items) == 1
        by_cat, _ = repo.list_equipment(category_id=_CAT)
        assert all(i.category_id == _CAT for i in by_cat)
    finally:
        s.close()


def test_search_and_sort(Session):
    s = Session()
    try:
        repo = EquipmentRepository(s)
        _create(repo, s, name="Crawler Crane XL")
        items, _ = repo.list_equipment(q="crawler")
        assert any("Crawler" in i.name for i in items)
        asc_items, _ = repo.list_equipment(sort_by="equipment_code", sort_dir="asc")
        codes = [i.equipment_code for i in asc_items]
        assert codes == sorted(codes)
    finally:
        s.close()


def test_category_and_model_repos(Session):
    s = Session()
    try:
        cat_repo = EquipmentCategoryRepository(s)
        model_repo = EquipmentModelRepository(s)
        # Seeded category/model are retrievable; bad ids return None.
        assert cat_repo.get_by_id(_CAT).id == _CAT
        assert cat_repo.get_by_id("bad") is None
        assert model_repo.get_by_id(_MODEL).id == _MODEL
        assert model_repo.get_by_id(uuid.uuid4()) is None

        # create() stages without committing.
        new_cat = cat_repo.create(
            tenant_id=_TENANT, code=f"CAT-{uuid.uuid4().hex[:6]}", name="Lifting"
        )
        s.flush()
        assert cat_repo.get_by_id(new_cat.id) is not None
        new_model = model_repo.create(
            tenant_id=_TENANT, category_id=_CAT,
            code=f"MOD-{uuid.uuid4().hex[:6]}", name="Grove GMK",
        )
        s.flush()
        assert model_repo.get_by_id(new_model.id) is not None
        s.rollback()
    finally:
        s.close()


def test_list_excludes_deleted_by_default(Session):
    s = Session()
    try:
        repo = EquipmentRepository(s)
        eq = _create(repo, s)
        repo.soft_delete(eq, deleted_by=None)
        s.commit()
        active, _ = repo.list_equipment(include_deleted=False)
        assert eq.id not in {i.id for i in active}
        withdel, _ = repo.list_equipment(include_deleted=True)
        assert eq.id in {i.id for i in withdel}
    finally:
        s.close()
