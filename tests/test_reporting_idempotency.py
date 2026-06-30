"""Tests for analytics consumer idempotency / replay-safety (Sprint 11)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.analytics.handlers import AnalyticsProjectionHandler
from app.events.dispatcher import PROCESSED, SKIPPED, Dispatcher
from app.events.envelope import EventEnvelope
from app.repositories.projection_repository import ShipmentPerformanceProjectionRepository
from reporting_sqlite import make_engine, seed_tenant

_TENANT = uuid.uuid4()
_engine = make_engine()
_Session = sessionmaker(bind=_engine, expire_on_commit=False)
_WHEN = datetime(2026, 6, 7, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    seed_tenant(_Session, tenant_id=_TENANT)


def _env():
    return EventEnvelope(event_id=uuid.uuid4(), tenant_id=_TENANT, aggregate_type="Shipment",
                         aggregate_id=uuid.uuid4(), aggregate_version=1, event_type="ShipmentCreated",
                         event_version=1, payload={}, occurred_at=_WHEN)


def _total(s):
    return ShipmentPerformanceProjectionRepository(s).get_or_create(_TENANT, _WHEN.date()).total_shipments


def test_dispatcher_dedup_applies_once():
    env = _env()
    handler = AnalyticsProjectionHandler()
    s = _Session()
    try:
        before = _total(s)
        dispatcher = Dispatcher(s, sleep=lambda *_: None)
        first = dispatcher.dispatch(handler, env)
        s.commit()
        second = dispatcher.dispatch(handler, env)  # replay
        s.commit()
        assert first == PROCESSED and second == SKIPPED
        assert _total(s) == before + 1  # applied exactly once
    finally:
        s.close()


def test_distinct_events_accumulate():
    handler = AnalyticsProjectionHandler()
    s = _Session()
    try:
        before = _total(s)
        d = Dispatcher(s, sleep=lambda *_: None)
        d.dispatch(handler, _env())
        d.dispatch(handler, _env())
        s.commit()
        assert _total(s) == before + 2
    finally:
        s.close()
