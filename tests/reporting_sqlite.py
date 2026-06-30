"""Shared helpers for SQLite-backed Reporting & Analytics tests.

Builds the projection tables + the event backbone (for real dispatcher
idempotency) + the Billing invoice/customer tables (for the AR-aging
read-through projection). The PostgreSQL-only regex currency CHECK (``~``) on
``invoices`` is stripped so SQLite can create it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.billing import Invoice, Payment
from app.models.customer import Customer
from app.models.event_store import DeadLetterEvent, EventStore, ProcessedEvent
from app.models.projection import (
    ARAgingProjection,
    ClaimsMetricsProjection,
    ComplianceMetricsProjection,
    FinancialSummaryProjection,
    NotificationDeliverabilityProjection,
    OperationsDashboardProjection,
    ProjectionHealth,
    ShipmentPerformanceProjection,
)
from app.models.tenant import Tenant
from app.models.user import User


@compiles(JSONB, "sqlite")
def _jsonb(element, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"


def _strip_pg_checks() -> None:
    for model in (Invoice, Payment):
        for c in list(model.__table__.constraints):
            if isinstance(c, CheckConstraint) and "~" in str(c.sqltext):
                model.__table__.constraints.discard(c)


_PROJECTIONS = [
    ProjectionHealth, ShipmentPerformanceProjection, FinancialSummaryProjection,
    ARAgingProjection, ClaimsMetricsProjection, ComplianceMetricsProjection,
    NotificationDeliverabilityProjection, OperationsDashboardProjection,
]


def make_engine():
    _strip_pg_checks()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Tenant.__table__, User.__table__, Customer.__table__,
            Invoice.__table__, Payment.__table__,
            EventStore.__table__, ProcessedEvent.__table__, DeadLetterEvent.__table__,
            AuditLog.__table__,
            *[m.__table__ for m in _PROJECTIONS],
        ],
    )
    return engine


def seed_tenant(SessionLocal, *, tenant_id):
    s = SessionLocal()
    try:
        if s.get(Tenant, tenant_id) is None:
            s.add(Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Rpt T",
                         status="active", isolation_mode="shared"))
            s.commit()
    finally:
        s.close()


def seed_customer(SessionLocal, *, tenant_id, customer_id):
    s = SessionLocal()
    try:
        if s.get(Customer, customer_id) is None:
            s.add(Customer(id=customer_id, tenant_id=tenant_id, code=f"C-{customer_id.hex[:6]}",
                           company_name="Acme", customer_type="corporate", status="active"))
            s.commit()
    finally:
        s.close()


def seed_invoice(SessionLocal, *, tenant_id, invoice_id, customer_id, total=Decimal("100"),
                 status="issued", due_date=None, currency="SAR"):
    s = SessionLocal()
    try:
        s.add(Invoice(id=invoice_id, tenant_id=tenant_id, invoice_number=f"INV-{invoice_id.hex[:6]}",
                      customer_id=customer_id, status=status, currency_code=currency,
                      subtotal_amount=total, total_amount=total, due_date=due_date))
        s.commit()
    finally:
        s.close()
