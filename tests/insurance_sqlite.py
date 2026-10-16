"""Shared helpers for SQLite-backed Insurance & Claims tests.

Builds the full cross-domain schema needed by claims (tenant, user, customer,
order, warehouse, equipment, shipment, compliance, insurance/claims tables).
"""

from __future__ import annotations

import uuid


import app.models  # noqa: F401
from app.models.compliance import ComplianceCheck, Permit
from app.models.customer import Customer
from app.models.equipment import Equipment, EquipmentCategory
from app.models.insurance import (
    Claim,
    CoverageRule,
    DamageReport,
    InsurancePolicy,
    LiabilityRecord,
)
from app.models.order import Order
from app.models.shipment import Shipment
from app.models.tenant import Tenant
from app.models.user import User
from app.models.warehouse import Warehouse
from sqlite_support import make_sqlite_engine
from sqlite_support import seed_tenant_user  # noqa: F401  (re-exported for tests)


def make_engine():
    return make_sqlite_engine(
        [
            Tenant,
            User,
            Customer,
            Order,
            Warehouse,
            EquipmentCategory,
            Equipment,
            Shipment,
            Permit,
            ComplianceCheck,
            InsurancePolicy,
            CoverageRule,
            Claim,
            DamageReport,
            LiabilityRecord,
        ]
    )


def seed_active_policy(SessionLocal, *, tenant_id, policy_id, covers_shipment=True,
                       covers_equipment=True, covers_third_party=True):
    s = SessionLocal()
    try:
        s.add(InsurancePolicy(
            id=policy_id, tenant_id=tenant_id, policy_number=f"POL-{policy_id.hex[:8]}",
            policy_type="cargo", status="active", currency_code="SAR",
            covers_shipment=covers_shipment, covers_equipment=covers_equipment,
            covers_third_party=covers_third_party,
        ))
        s.commit()
    finally:
        s.close()


def seed_shipment(SessionLocal, *, tenant_id, client_user_id, shipment_id, status="failed"):
    s = SessionLocal()
    try:
        wid = uuid.uuid4()
        s.add(Warehouse(id=wid, tenant_id=tenant_id, code=f"W{wid.hex[:6]}", name="d",
                        address_line1="1", city="R", country="SA",
                        capacity_weight_kg=1e6, capacity_volume_m3=1e6))
        s.commit()
        s.add(Shipment(id=shipment_id, tenant_id=tenant_id, reference_code=f"S{shipment_id.hex[:6]}",
                       client_id=client_user_id, origin_warehouse_id=wid, destination_warehouse_id=wid,
                       status=status, weight_kg=100, volume_m3=2))
        s.commit()
    finally:
        s.close()


def seed_equipment(SessionLocal, *, tenant_id, category_id, equipment_id, status="active"):
    s = SessionLocal()
    try:
        if s.get(EquipmentCategory, category_id) is None:
            s.add(EquipmentCategory(id=category_id, tenant_id=tenant_id, code=f"C{category_id.hex[:6]}", name="Earth"))
            s.commit()
        s.add(Equipment(id=equipment_id, tenant_id=tenant_id, equipment_code=f"EQP-{equipment_id.hex[:8]}",
                        asset_tag=f"TAG-{equipment_id.hex[:8]}", category_id=category_id, name="Excavator",
                        ownership_type="owned", status=status, availability_status="available"))
        s.commit()
    finally:
        s.close()


def seed_compliance_check(SessionLocal, *, tenant_id, check_id, shipment_id=None, status="failed"):
    s = SessionLocal()
    try:
        s.add(ComplianceCheck(id=check_id, tenant_id=tenant_id, shipment_id=shipment_id,
                              check_type="permit_required", status=status, blocking=True))
        s.commit()
    finally:
        s.close()
