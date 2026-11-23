"""Shared helpers for SQLite-backed Equipment tests.

The equipment tables carry no PostgreSQL-only regex CHECK, so ``create_all``
works directly. These helpers build the minimal schema and seed the tenant,
warehouse, category, and model that an equipment unit references.
"""

from __future__ import annotations

import uuid


import app.models  # noqa: F401 — register all models
from app.models.equipment import Equipment, EquipmentCategory, EquipmentModel
from app.models.tenant import Tenant
from app.models.warehouse import Warehouse
from sqlite_support import make_sqlite_engine


def make_engine():
    return make_sqlite_engine(
        [
            Tenant,
            Warehouse,
            EquipmentCategory,
            EquipmentModel,
            Equipment,
        ]
    )


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
