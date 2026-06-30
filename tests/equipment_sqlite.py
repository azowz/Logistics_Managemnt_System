"""Shared helpers for SQLite-backed Equipment tests.

The equipment tables carry no PostgreSQL-only regex CHECK, so ``create_all``
works directly. These helpers build the minimal schema and seed the tenant,
warehouse, category, and model that an equipment unit references.
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register all models
from app.db.base import Base
from app.models.equipment import Equipment, EquipmentCategory, EquipmentModel
from app.models.tenant import Tenant
from app.models.warehouse import Warehouse


@compiles(JSONB, "sqlite")
def _render_jsonb_as_json(element, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"


def make_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Tenant.__table__,
            Warehouse.__table__,
            EquipmentCategory.__table__,
            EquipmentModel.__table__,
            Equipment.__table__,
        ],
    )
    return engine


def seed_prereqs(
    SessionLocal,
    *,
    tenant_id: uuid.UUID,
    category_id: uuid.UUID,
    model_id: uuid.UUID,
    warehouse_id: uuid.UUID,
) -> None:
    s = SessionLocal()
    try:
        if s.get(Tenant, tenant_id) is None:
            s.add(
                Tenant(
                    id=tenant_id,
                    slug=f"t-{tenant_id.hex[:8]}",
                    name="Equipment Tenant",
                    status="active",
                    isolation_mode="shared",
                )
            )
            s.commit()
        if s.get(EquipmentCategory, category_id) is None:
            s.add(
                EquipmentCategory(
                    id=category_id,
                    tenant_id=tenant_id,
                    code=f"CAT-{category_id.hex[:6]}",
                    name="Earthmoving",
                )
            )
            s.commit()
        if s.get(EquipmentModel, model_id) is None:
            s.add(
                EquipmentModel(
                    id=model_id,
                    tenant_id=tenant_id,
                    category_id=category_id,
                    code=f"MOD-{model_id.hex[:6]}",
                    name="CAT 320",
                    manufacturer="Caterpillar",
                    model_name="320",
                    model_year=2022,
                )
            )
            s.commit()
        if s.get(Warehouse, warehouse_id) is None:
            s.add(
                Warehouse(
                    id=warehouse_id,
                    tenant_id=tenant_id,
                    code=f"WH-{warehouse_id.hex[:6]}",
                    name="Depot",
                    address_line1="1 St",
                    city="Riyadh",
                    country="SA",
                    capacity_weight_kg=1_000_000,
                    capacity_volume_m3=1_000_000,
                )
            )
            s.commit()
    finally:
        s.close()
