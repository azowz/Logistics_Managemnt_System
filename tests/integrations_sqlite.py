"""Shared helpers for SQLite-backed Integrations & Webhooks tests.

Builds the six ``integration``/``webhook`` tables plus the event backbone (for real
dispatcher idempotency + outbox append audit) and tenant/user. JSONB compiles to JSON
on SQLite; the integration models use no PostgreSQL regex CHECKs, so none need stripping.
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register all mappers)
from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.event_store import DeadLetterEvent, EventStore, ProcessedEvent
from app.models.integration import (
    InboundIntegrationEvent,
    IntegrationPartner,
    PartnerApiKey,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)
from app.models.tenant import Tenant
from app.models.user import User


@compiles(JSONB, "sqlite")
def _jsonb(element, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"


_INTEGRATION = [
    IntegrationPartner, PartnerApiKey, WebhookSubscription,
    WebhookDelivery, WebhookDeliveryAttempt, InboundIntegrationEvent,
]


def make_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Tenant.__table__, User.__table__,
            EventStore.__table__, ProcessedEvent.__table__, DeadLetterEvent.__table__,
            AuditLog.__table__,
            *[m.__table__ for m in _INTEGRATION],
        ],
    )
    return engine


def seed_tenant_user(SessionLocal, *, tenant_id, user_id=None):
    s = SessionLocal()
    try:
        if s.get(Tenant, tenant_id) is None:
            s.add(Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Intg T",
                         status="active", isolation_mode="shared"))
            s.commit()
        if user_id is not None and s.get(User, user_id) is None:
            s.add(User(id=user_id, tenant_id=tenant_id, email=f"u-{user_id.hex[:8]}@t.test",
                       hashed_password="x", role="admin", is_active=True))
            s.commit()
    finally:
        s.close()


def seed_partner(SessionLocal, *, tenant_id, partner_id, status="active", partner_type="carrier"):
    s = SessionLocal()
    try:
        if s.get(IntegrationPartner, partner_id) is None:
            s.add(IntegrationPartner(id=partner_id, tenant_id=tenant_id, name=f"P-{partner_id.hex[:6]}",
                                     partner_type=partner_type, status=status))
            s.commit()
    finally:
        s.close()
