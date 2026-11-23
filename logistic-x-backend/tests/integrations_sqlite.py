"""Shared helpers for SQLite-backed Integrations & Webhooks tests.

Builds the six ``integration``/``webhook`` tables plus the event backbone (for real
dispatcher idempotency + outbox append audit) and tenant/user.
"""

from __future__ import annotations

import app.models  # noqa: F401  (register all mappers)
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
from sqlite_support import make_sqlite_engine, seed_tenant_user as _seed_tenant_user


_INTEGRATION = [
    IntegrationPartner, PartnerApiKey, WebhookSubscription,
    WebhookDelivery, WebhookDeliveryAttempt, InboundIntegrationEvent,
]


def make_engine():
    return make_sqlite_engine(
        [
            Tenant,
            User,
            EventStore,
            ProcessedEvent,
            DeadLetterEvent,
            AuditLog,
            *_INTEGRATION,
        ]
    )


def seed_tenant_user(SessionLocal, *, tenant_id, user_id=None):
    _seed_tenant_user(SessionLocal, tenant_id=tenant_id, user_id=user_id, role="admin")


def seed_partner(SessionLocal, *, tenant_id, partner_id, status="active", partner_type="carrier"):
    s = SessionLocal()
    try:
        if s.get(IntegrationPartner, partner_id) is None:
            s.add(IntegrationPartner(id=partner_id, tenant_id=tenant_id, name=f"P-{partner_id.hex[:6]}",
                                     partner_type=partner_type, status=status))
            s.commit()
    finally:
        s.close()
