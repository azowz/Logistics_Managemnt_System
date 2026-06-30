"""Service tests for NotificationService — API path (SQLite + patched ctx)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import NotificationChannel, NotificationPriority, NotificationStatus
from app.services.exceptions import ConflictError, NotFoundError, StatusTransitionError, ValidationError
from app.services.notification_service import NotificationService
from notifications_sqlite import make_engine, seed_template, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()

_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT, user_id=_USER)


@pytest.fixture(autouse=True)
def ctx():
    with (
        patch("app.services.notification_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.notification_service.get_current_user_id", return_value=_USER),
        patch("app.services.notification_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        yield


def _svc() -> NotificationService:
    return NotificationService(_Session())


# --- templates ---


def test_template_crud_and_lifecycle():
    svc = _svc()
    t = svc.create_template(template_code="welcome", name="Welcome", channel=NotificationChannel.IN_APP,
                            body_template="Hi {name}", event_type="ClaimCreated")
    assert t.active is True
    assert svc.deactivate_template(t.id).active is False
    assert svc.activate_template(t.id).active is True
    updated = svc.update_template(t.id, name="Welcome v2")
    assert updated.name == "Welcome v2"


def test_template_duplicate_code_conflict():
    svc = _svc()
    svc.create_template(template_code="dup-tpl", name="A", channel=NotificationChannel.IN_APP, body_template="b")
    with pytest.raises(ConflictError):
        svc.create_template(template_code="dup-tpl", name="B", channel=NotificationChannel.IN_APP, body_template="b")


def test_template_delete_restore():
    svc = _svc()
    t = svc.create_template(template_code="del-tpl", name="D", channel=NotificationChannel.IN_APP, body_template="b")
    svc.delete_template(t.id)
    with pytest.raises(NotFoundError):
        svc.get_template(t.id)
    restored = svc.restore_template(t.id)
    assert restored.is_deleted is False


# --- notifications ---


def test_create_in_app_notification_and_send():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="Hello there")
    assert n.status == NotificationStatus.PENDING
    sent = svc.send_notification(n.id)
    assert sent.status == NotificationStatus.SENT and sent.sent_at is not None


def test_create_requires_recipient_target():
    svc = _svc()
    with pytest.raises(ValidationError):
        svc.create_notification(channel=NotificationChannel.IN_APP, body="x")


def test_create_unknown_recipient_user_rejected():
    svc = _svc()
    with pytest.raises(ValidationError):
        svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=uuid.uuid4(), body="x")


def test_email_notification_send_marks_failed_no_provider():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.EMAIL, recipient_email="a@b.com", body="hi")
    sent = svc.send_notification(n.id)
    # email provider is a null adapter -> skipped -> notification failed, never silently sent
    assert sent.status == NotificationStatus.FAILED
    assert sent.last_error and "configured" in sent.last_error
    attempts = svc.list_delivery_attempts(n.id)
    assert len(attempts) == 1 and attempts[0].status.value == "skipped"


def test_failed_notification_can_be_retried():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.EMAIL, recipient_email="a@b.com", body="hi")
    svc.send_notification(n.id)
    retried = svc.retry_notification(n.id)
    # still no provider -> fails again, retry_count incremented, second attempt recorded
    assert retried.status == NotificationStatus.FAILED
    assert retried.retry_count == 2
    assert len(svc.list_delivery_attempts(n.id)) == 2


def test_mark_read_is_idempotent():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi")
    svc.send_notification(n.id)
    read = svc.mark_read(n.id)
    assert read.status == NotificationStatus.READ and read.read_at is not None
    first_read_at = read.read_at
    again = svc.mark_read(n.id)  # no-op, not re-marked
    assert again.read_at == first_read_at


def test_cancel_notification():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi")
    cancelled = svc.cancel_notification(n.id, reason="dupe")
    assert cancelled.status == NotificationStatus.CANCELLED


def test_cannot_send_cancelled():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi")
    svc.cancel_notification(n.id)
    with pytest.raises(ValidationError):
        svc.send_notification(n.id)


def test_cannot_resend_sent():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi")
    svc.send_notification(n.id)
    with pytest.raises(ValidationError):
        svc.send_notification(n.id)


def test_queue_then_send():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi")
    q = svc.queue_notification(n.id)
    assert q.status == NotificationStatus.QUEUED and q.queued_at is not None
    assert svc.send_notification(n.id).status == NotificationStatus.SENT


def test_create_with_template_rendering():
    svc = _svc()
    svc.create_template(template_code="evt-tpl", name="E", channel=NotificationChannel.IN_APP,
                        body_template="Hello {name}", event_type="InvoicePaid")
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER,
                                event_type="InvoicePaid", variables={"name": "Sam"})
    assert n.body == "Hello Sam"


def test_manual_idempotency_key_conflict():
    svc = _svc()
    svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi",
                            idempotency_key="manual-key-1")
    with pytest.raises(ConflictError):
        svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi",
                                idempotency_key="manual-key-1")


def test_list_and_unread():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="unread me")
    svc.send_notification(n.id)
    from app.schemas.notification import NotificationListParams
    page = svc.list_notifications(NotificationListParams(recipient_user_id=_USER, page=1, size=100))
    assert page.total >= 1
    unread = svc.list_unread(_USER, page=1, size=100)
    assert unread.total >= 1
