"""Shared helpers for SQLite-backed Notifications tests.

Builds the schema needed by notifications (tenant, user, the 3 notification
tables) plus the event backbone (event_store, processed_events, audit_log,
dead_letter_events) so one test can exercise real dispatcher-level idempotency.
The PostgreSQL-only regex email CHECK (``~``) is stripped so SQLite can create
the ``notifications`` table.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.event_store import DeadLetterEvent, EventStore, ProcessedEvent
from app.models.notification import (
    Notification,
    NotificationDeliveryAttempt,
    NotificationTemplate,
)
from app.models.tenant import Tenant
from app.models.user import User


@compiles(JSONB, "sqlite")
def _jsonb(element, compiler, **kw):  # noqa: ANN001, ANN201
    return "JSON"


def _strip_pg_checks() -> None:
    for c in list(Notification.__table__.constraints):
        if isinstance(c, CheckConstraint) and "~" in str(c.sqltext):
            Notification.__table__.constraints.discard(c)


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
            Tenant.__table__, User.__table__,
            NotificationTemplate.__table__, Notification.__table__,
            NotificationDeliveryAttempt.__table__,
            EventStore.__table__, ProcessedEvent.__table__,
            DeadLetterEvent.__table__, AuditLog.__table__,
        ],
    )
    return engine


def seed_tenant_user(SessionLocal, *, tenant_id, user_id):
    s = SessionLocal()
    try:
        if s.get(Tenant, tenant_id) is None:
            s.add(Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Notif T",
                         status="active", isolation_mode="shared"))
            s.commit()
        if s.get(User, user_id) is None:
            s.add(User(id=user_id, tenant_id=tenant_id, email=f"u-{user_id.hex[:8]}@t.test",
                       hashed_password="x", role="manager", is_active=True))
            s.commit()
    finally:
        s.close()


def seed_template(SessionLocal, *, tenant_id, template_id, code="welcome", channel="in_app",
                  event_type=None, active=True, subject="Hi {name}", body="Hello {name}",
                  variables_schema=None):
    s = SessionLocal()
    try:
        s.add(NotificationTemplate(
            id=template_id, tenant_id=tenant_id, template_code=code, name=code.title(),
            channel=channel, subject_template=subject, body_template=body, language="en",
            active=active, event_type=event_type, variables_schema=variables_schema,
        ))
        s.commit()
    finally:
        s.close()
