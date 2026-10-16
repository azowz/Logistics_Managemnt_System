"""Shared helpers for SQLite-backed Notifications tests.

Builds the schema needed by notifications (tenant, user, the 3 notification
tables) plus the event backbone (event_store, processed_events, audit_log,
dead_letter_events) so one test can exercise real dispatcher-level idempotency.
"""

from __future__ import annotations

import app.models  # noqa: F401
from app.models.audit_log import AuditLog
from app.models.event_store import DeadLetterEvent, EventStore, ProcessedEvent
from app.models.notification import (
    Notification,
    NotificationDeliveryAttempt,
    NotificationTemplate,
)
from app.models.tenant import Tenant
from app.models.user import User
from sqlite_support import make_sqlite_engine
from sqlite_support import seed_tenant_user  # noqa: F401  (re-exported for tests)


def make_engine():
    return make_sqlite_engine(
        [
            Tenant,
            User,
            NotificationTemplate,
            Notification,
            NotificationDeliveryAttempt,
            EventStore,
            ProcessedEvent,
            DeadLetterEvent,
            AuditLog,
        ]
    )


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
