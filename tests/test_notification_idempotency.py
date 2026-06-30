"""Tests for idempotent event-driven notification creation (Sprint 10).

Two layers are proven:
  1. Domain-level — the per-recipient idempotency key + unique constraint stops
     a duplicate notification for the same (tenant, event, channel, recipient).
  2. Consumer-level — the real :class:`Dispatcher` dedups on ``processed_events``
     so a replayed envelope is skipped entirely.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.events.dispatcher import PROCESSED, SKIPPED, Dispatcher
from app.events.envelope import EventEnvelope
from app.events.shipment_events import ShipmentDelivered
from app.models.notification import Notification
from app.notifications.handlers import NotificationEventHandler
from app.repositories.notification_repository import NotificationRepository
from notifications_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()

_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant_user(_Session, tenant_id=_TENANT, user_id=_USER)


def _envelope():
    agg = uuid.uuid4()
    evt = ShipmentDelivered(shipment_id=agg, tenant_id=_TENANT, delivered_at=None, previous_status="in_transit")
    env = EventEnvelope.create(evt, tenant_id=_TENANT, aggregate_id=agg, aggregate_version=1,
                               aggregate_type="Shipment", user_id=_USER)
    return evt, env


def _count_for_event(session, event_id) -> int:
    items, _ = NotificationRepository(session).list_notifications(event_type="ShipmentDelivered", limit=200)
    return len([n for n in items if n.event_id == event_id])


def test_domain_level_idempotency_no_duplicate_on_replay():
    """Calling the handler twice for the same event creates exactly one row."""
    evt, env = _envelope()
    with (
        patch("app.services.notification_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.notification_service.get_current_user_id", return_value=_USER),
        patch("app.services.notification_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        handler = NotificationEventHandler()
        s = _Session()
        try:
            handler.handle(evt, env, s)
            s.commit()
            handler.handle(evt, env, s)  # replay
            s.commit()
            assert _count_for_event(s, env.event_id) == 1
        finally:
            s.close()


def test_consumer_level_idempotency_via_dispatcher():
    """The real Dispatcher skips a replayed envelope (processed_events dedup)."""
    evt, env = _envelope()
    handler = NotificationEventHandler()
    with (
        patch("app.services.notification_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.notification_service.get_current_user_id", return_value=_USER),
    ):
        s = _Session()
        try:
            dispatcher = Dispatcher(s, sleep=lambda *_: None)
            first = dispatcher.dispatch(handler, env)
            s.commit()
            second = dispatcher.dispatch(handler, env)  # replay
            s.commit()
            assert first == PROCESSED
            assert second == SKIPPED
            assert _count_for_event(s, env.event_id) == 1
        finally:
            s.close()


def test_concurrent_race_integrity_error_is_idempotent_skip():
    """L3: if the idempotency-key SELECT misses but the row already exists, the
    INSERT's IntegrityError is swallowed as an idempotent skip (not a failed event)."""
    from app.models.enums import NotificationChannel
    from app.repositories.notification_repository import NotificationRepository
    from app.services.notification_service import NotificationService

    evt, env = _envelope()
    key = f"{env.event_id}:in_app:{_USER}"
    with (
        patch("app.services.notification_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.notification_service.get_current_user_id", return_value=_USER),
        patch("app.services.notification_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        s = _Session()
        try:
            # Pre-insert the row a "concurrent" consumer would have written.
            NotificationRepository(s).create(
                tenant_id=_TENANT, idempotency_key=key, event_id=env.event_id,
                event_type="ShipmentDelivered", channel=NotificationChannel.IN_APP,
                body="race winner", recipient_user_id=_USER, status="pending",
            )
            s.commit()
            svc = NotificationService(s)
            # Force the SELECT-miss so the code path reaches the INSERT + IntegrityError.
            with patch.object(svc, "enforce_idempotency", return_value=None):
                created = svc.create_notifications_from_event(
                    evt, env, channel=NotificationChannel.IN_APP)
            s.commit()
            assert created == []  # idempotent skip, no exception
            assert _count_for_event(s, env.event_id) == 1
        finally:
            s.close()


def test_distinct_events_create_distinct_notifications():
    with (
        patch("app.services.notification_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.notification_service.get_current_user_id", return_value=_USER),
        patch("app.services.notification_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        handler = NotificationEventHandler()
        s = _Session()
        try:
            _, env1 = _envelope()
            _, env2 = _envelope()
            handler.handle(env1, env1, s)
            handler.handle(env2, env2, s)
            s.commit()
            assert _count_for_event(s, env1.event_id) == 1
            assert _count_for_event(s, env2.event_id) == 1
        finally:
            s.close()
