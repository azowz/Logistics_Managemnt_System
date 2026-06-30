"""Tests for channel providers + delivery-attempt recording (Sprint 10)."""

from __future__ import annotations

import types
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.enums import DeliveryAttemptStatus, NotificationChannel, NotificationStatus
from app.notifications.providers import (
    DeliveryResult,
    EmailNotificationProvider,
    InAppNotificationProvider,
    ProviderRegistry,
    WebhookNotificationProvider,
    get_provider_registry,
)
from app.services.notification_service import NotificationService
from notifications_sqlite import make_engine, seed_tenant_user

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


# --- provider units -------------------------------------------------------


def test_in_app_provider_is_configured_and_succeeds():
    p = InAppNotificationProvider()
    assert p.is_configured() is True
    res = p.send(types.SimpleNamespace(id=uuid.uuid4()))
    assert res.succeeded and res.status == DeliveryAttemptStatus.SUCCEEDED


def test_null_providers_not_configured_and_skip():
    for P in (EmailNotificationProvider, WebhookNotificationProvider):
        p = P()
        assert p.is_configured() is False
        res = p.send(types.SimpleNamespace(id=uuid.uuid4()))
        assert res.status == DeliveryAttemptStatus.SKIPPED
        assert res.error_code == "provider_not_configured"
        assert not res.succeeded


def test_registry_default_channels():
    reg = get_provider_registry()
    assert reg.get(NotificationChannel.IN_APP).is_configured() is True
    assert reg.get(NotificationChannel.SMS).is_configured() is False


# --- delivery through the service -----------------------------------------


def _svc(registry=None):
    return NotificationService(_Session(), provider_registry=registry)


def test_in_app_delivery_records_succeeded_attempt():
    svc = _svc()
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi")
    svc.send_notification(n.id)
    attempts = svc.list_delivery_attempts(n.id)
    assert len(attempts) == 1
    assert attempts[0].status == DeliveryAttemptStatus.SUCCEEDED
    assert attempts[0].provider == "in_app"


def test_missing_provider_marks_failed_not_silent_success():
    # A registry with NO provider for the channel must not silently succeed.
    empty = ProviderRegistry(providers={})
    svc = _svc(empty)
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi")
    sent = svc.send_notification(n.id)
    assert sent.status == NotificationStatus.FAILED
    attempts = svc.list_delivery_attempts(n.id)
    assert attempts[0].status == DeliveryAttemptStatus.SKIPPED
    assert attempts[0].error_code == "no_provider"


def test_configured_failure_provider_records_failed():
    class _FailingProvider:
        channel = NotificationChannel.IN_APP
        name = "boom"

        def is_configured(self):
            return True

        def send(self, notification):
            return DeliveryResult(status=DeliveryAttemptStatus.FAILED, provider=self.name,
                                  error_code="boom", error_message="kaboom")

    reg = ProviderRegistry(providers={NotificationChannel.IN_APP: _FailingProvider()})
    svc = _svc(reg)
    n = svc.create_notification(channel=NotificationChannel.IN_APP, recipient_user_id=_USER, body="hi")
    sent = svc.send_notification(n.id)
    assert sent.status == NotificationStatus.FAILED and sent.last_error == "kaboom"
    assert svc.list_delivery_attempts(n.id)[0].status == DeliveryAttemptStatus.FAILED
