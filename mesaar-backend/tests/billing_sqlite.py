"""Shared helpers for SQLite-backed Billing & Settlements tests.

Builds the full cross-domain schema needed by billing (tenant, user, customer,
order, warehouse, equipment, shipment, claims, billing tables).
"""

from __future__ import annotations

import uuid


import app.models  # noqa: F401
from app.models.billing import (
    Invoice,
    InvoiceLine,
    Payment,
    Payout,
    Penalty,
    Quote,
    Settlement,
)
from app.models.customer import Customer
from app.models.equipment import Equipment, EquipmentCategory
from app.models.insurance import Claim, InsurancePolicy
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
            InsurancePolicy,
            Claim,
            Quote,
            Invoice,
            InvoiceLine,
            Payment,
            Settlement,
            Payout,
            Penalty,
        ]
    )


def seed_customer(SessionLocal, *, tenant_id, customer_id):
    s = SessionLocal()
    try:
        if s.get(Customer, customer_id) is None:
            s.add(Customer(id=customer_id, tenant_id=tenant_id, code=f"CUST-{customer_id.hex[:6]}",
                           company_name="Acme Co", customer_type="corporate", status="active"))
            s.commit()
    finally:
        s.close()


def seed_order(SessionLocal, *, tenant_id, order_id, customer_id=None):
    s = SessionLocal()
    try:
        if s.get(Order, order_id) is None:
            s.add(Order(id=order_id, tenant_id=tenant_id, order_number=f"ORD-{order_id.hex[:6]}",
                        customer_id=customer_id, status="draft"))
            s.commit()
    finally:
        s.close()


def seed_shipment(SessionLocal, *, tenant_id, client_user_id, shipment_id, status="delivered"):
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


def seed_claim(SessionLocal, *, tenant_id, claim_id, status="approved", approved_amount=1000,
               claim_type="shipment_loss"):
    s = SessionLocal()
    try:
        s.add(Claim(id=claim_id, tenant_id=tenant_id, claim_number=f"CLM-{claim_id.hex[:8]}",
                    claim_type=claim_type, status=status, severity="medium",
                    claimed_amount=approved_amount, approved_amount=approved_amount, currency_code="SAR"))
        s.commit()
    finally:
        s.close()
