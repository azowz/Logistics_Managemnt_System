"""ORM-level tests for Notifications models (SQLite)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.notification import Notification, NotificationDeliveryAttempt, NotificationTemplate
from notifications_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def test_template_defaults_and_persist(Session):
    s = Session()
    try:
        t = NotificationTemplate(tenant_id=_TENANT, template_code="tpl-1", name="T1",
                                 channel="in_app", body_template="Hello")
        s.add(t)
        s.commit()
        s.refresh(t)
        assert t.id is not None and t.version == 1 and t.active is True and t.language == "en"
    finally:
        s.close()


def test_notification_persist_and_enum_storage(Session):
    s = Session()
    try:
        n = Notification(tenant_id=_TENANT, idempotency_key="k1", channel="in_app",
                         body="Body", recipient_user_id=_USER, status="pending", priority="high")
        s.add(n)
        s.commit()
        raw = s.execute(
            __import__("sqlalchemy").text("SELECT status, priority FROM notifications WHERE idempotency_key='k1'")
        ).first()
        assert raw == ("pending", "high")
        assert n.retry_count == 0
    finally:
        s.close()


def test_idempotency_key_unique_per_tenant(Session):
    s = Session()
    try:
        s.add(Notification(tenant_id=_TENANT, idempotency_key="dup", channel="in_app",
                           body="b", recipient_user_id=_USER))
        s.commit()
        s.add(Notification(tenant_id=_TENANT, idempotency_key="dup", channel="in_app",
                           body="b2", recipient_user_id=_USER))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
    finally:
        s.close()


def test_recipient_target_required(Session):
    s = Session()
    try:
        s.add(Notification(tenant_id=_TENANT, idempotency_key="no-target", channel="in_app", body="b"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
    finally:
        s.close()


def test_delivery_attempt_persist(Session):
    s = Session()
    try:
        n = Notification(tenant_id=_TENANT, idempotency_key="k-att", channel="email",
                         body="b", recipient_email="a@b.com")
        s.add(n)
        s.commit()
        att = NotificationDeliveryAttempt(tenant_id=_TENANT, notification_id=n.id, channel="email",
                                          provider="email_null", status="skipped", attempt_number=1)
        s.add(att)
        s.commit()
        assert att.id is not None and att.attempt_number == 1
    finally:
        s.close()


def test_template_soft_delete_roundtrip(Session):
    s = Session()
    try:
        t = NotificationTemplate(tenant_id=_TENANT, template_code="tpl-sd", name="T", channel="in_app",
                                 body_template="x")
        s.add(t)
        s.commit()
        t.soft_delete()
        s.commit()
        assert t.is_deleted is True
        t.restore()
        s.commit()
        assert t.is_deleted is False
    finally:
        s.close()
