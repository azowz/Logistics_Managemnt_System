"""Shared helpers for SQLite-backed Compliance tests.

Builds a cross-domain schema (tenant, user, warehouse, equipment, vehicle,
shipment + the six compliance tables).
"""

from __future__ import annotations

import uuid


import app.models  # noqa: F401
from app.models.compliance import (
    AxleWeightProfile,
    ComplianceCheck,
    Escort,
    OperatorCertification,
    Permit,
    RouteRestriction,
)
from app.models.driver import Driver
from app.models.equipment import Equipment, EquipmentCategory, EquipmentModel
from app.models.shipment import Shipment
from app.models.tenant import Tenant
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.warehouse import Warehouse
from sqlite_support import make_sqlite_engine
from sqlite_support import seed_tenant_user  # noqa: F401  (re-exported for tests)


def make_engine():
    return make_sqlite_engine(
        [
            Tenant,
            User,
            Warehouse,
            EquipmentCategory,
            EquipmentModel,
            Equipment,
            Vehicle,
            Driver,
            Shipment,
            RouteRestriction,
            Permit,
            Escort,
            AxleWeightProfile,
            ComplianceCheck,
            OperatorCertification,
        ]
    )


def seed_shipment_with_equipment(
    SessionLocal, *, tenant_id, client_user_id, category_id, equipment_id, shipment_id,
    requires_permit=False, requires_escort=False, hazardous=False, eq_status="active",
):
    """Seed a warehouse, equipment (with flags), and a shipment referencing it."""
    s = SessionLocal()
    try:
        wid = uuid.uuid4()
        s.add(Warehouse(id=wid, tenant_id=tenant_id, code=f"WH-{wid.hex[:6]}", name="D",
                        address_line1="1", city="Riyadh", country="SA",
                        capacity_weight_kg=1_000_000, capacity_volume_m3=1_000_000))
        if s.get(EquipmentCategory, category_id) is None:
            s.add(EquipmentCategory(id=category_id, tenant_id=tenant_id,
                                    code=f"CAT-{category_id.hex[:6]}", name="Earth"))
        s.commit()
        s.add(Equipment(
            id=equipment_id, tenant_id=tenant_id, equipment_code=f"EQP-{equipment_id.hex[:8]}",
            asset_tag=f"TAG-{equipment_id.hex[:8]}", category_id=category_id, name="Excavator",
            ownership_type="owned", status=eq_status, availability_status="available",
            requires_permit=requires_permit, requires_escort=requires_escort, hazardous=hazardous,
            weight_kg=8000, volume_m3=30,
        ))
        s.commit()
        s.add(Shipment(
            id=shipment_id, tenant_id=tenant_id, reference_code=f"SHP-{shipment_id.hex[:8]}",
            client_id=client_user_id, origin_warehouse_id=wid, destination_warehouse_id=wid,
            equipment_id=equipment_id, status="ready", weight_kg=10000, volume_m3=50,
        ))
        s.commit()
    finally:
        s.close()
