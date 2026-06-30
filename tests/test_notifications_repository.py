"""Tests for notification repositories: no-commit, query helpers, idempotency lookup."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import NotificationChannel, NotificationStatus
from app.repositories.errors import NotFoundError
from app.repositories.notification_repository import (
    NotificationDeliveryAttemptRepository,
    NotificationRepository,
    NotificationTemplateRepository,
)
from notifications_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


@pytest.fixture(scope="module")
def Session():
    engine = make_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    seed_tenant_user(SessionLocal, tenant_id=_TENANT, user_id=_USER)
    return SessionLocal


def test_template_no_commit_and_lookup(Session):
    s = Session()
    try:
        repo = NotificationTemplateRepository(s)
        t = repo.create(tenant_id=_TENANT, template_code="nc", name="N", channel=NotificationChannel.IN_APP,
                        body_template="b")
        tid = t.id
        s.rollback()
        assert repo.get_by_id(tid) is None
        with pytest.raises(NotFoundError):
            repo.get_by_id_or_raise(uuid.uuid4())
    finally:
        s.close()


def test_template_get_by_code_and_active_for_event(Session):
    s = Session()
    try:
        repo = NotificationTemplateRepository(s)
        repo.create(tenant_id=_TENANT, template_code="evt", name="E", channel=NotificationChannel.IN_APP,
                    body_template="b", event_type="ShipmentDelayed", active=True)
        s.commit()
        assert repo.get_by_code("evt") is not None
        assert repo.get_active_for_event("ShipmentDelayed", NotificationChannel.IN_APP) is not None
        assert repo.get_active_for_event("ShipmentDelayed", NotificationChannel.EMAIL) is None
        items, total = repo.list_templates(channel=NotificationChannel.IN_APP, limit=10)
        assert total >= 1
    finally:
        s.close()


def test_notification_idempotency_lookup_and_lists(Session):
    s = Session()
    try:
        repo = NotificationRepository(s)
        repo.create(tenant_id=_TENANT, idempotency_key="evt:in_app:u1", channel=NotificationChannel.IN_APP,
                    body="b", recipient_user_id=_USER, status=NotificationStatus.PENDING, event_type="ClaimCreated")
        s.commit()
        assert repo.get_by_event_recipient_key("evt:in_app:u1") is not None
        assert repo.get_by_event_recipient_key("missing") is None
        unread, total = repo.list_unread_for_user(_USER)
        assert total >= 1
        assert len(repo.list_pending(limit=10)) >= 1
        items, t2 = repo.list_notifications(event_type="ClaimCreated")
        assert t2 >= 1
    finally:
        s.close()


def test_failed_retryable_and_attempt_numbering(Session):
    s = Session()
    try:
        nrepo = NotificationRepository(s)
        n = nrepo.create(tenant_id=_TENANT, idempotency_key="fail-1", channel=NotificationChannel.EMAIL,
                         body="b", recipient_email="a@b.com", status=NotificationStatus.FAILED, retry_count=1)
        s.commit()
        retryable = nrepo.list_failed_retryable(max_retries=5)
        assert any(x.id == n.id for x in retryable)
        arepo = NotificationDeliveryAttemptRepository(s)
        assert arepo.next_attempt_number(n.id) == 1
        arepo.create(tenant_id=_TENANT, notification_id=n.id, channel=NotificationChannel.EMAIL,
                     status="failed", attempt_number=1)
        s.commit()
        assert arepo.next_attempt_number(n.id) == 2
        assert len(arepo.list_attempts_for_notification(n.id)) == 1
    finally:
        s.close()
