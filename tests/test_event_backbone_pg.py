"""Postgres-only integration tests for the event backbone (M2 CI gate).

Exercises the real append → outbox-relay → idempotent-dispatch → projection path,
optimistic-concurrency conflicts, replay, and RLS isolation against a live
PostgreSQL. Requires the **application** ``DATABASE_URL`` to point at PostgreSQL
(so the relay's ``session_scope``/engine use it) and is skipped otherwise. CI
must run this with a non-superuser role for the RLS assertions to be meaningful.
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

_DB = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _DB.startswith("postgres"),
    reason="event-backbone integration requires a PostgreSQL DATABASE_URL",
)

NIL = "00000000-0000-0000-0000-000000000000"


# ---- a self-contained test event + projection -------------------------
@dataclasses.dataclass(frozen=True, slots=True)
class WidgetCreated:
    event_type = "WidgetCreated"
    event_version = 1
    widget_id: uuid.UUID
    name: str


@pytest.fixture()
def backbone():
    """Create schema, RLS, a fresh registry/bus, and a recording projection."""
    from sqlalchemy import text

    from app.db.base import Base
    from app.db.session import engine, session_scope
    from app.db.tenant import PLATFORM_TENANT_ID
    import app.models  # noqa: F401 - ensure all models import
    import app.models.tenant, app.models.user, app.models.driver, app.models.vehicle  # noqa: F401
    import app.models.warehouse, app.models.shipment, app.models.shipment_tracking_event  # noqa: F401
    import app.models.event_store, app.models.audit_log  # noqa: F401
    from app.events.bus import InProcessEventBus, BaseEventHandler
    from app.events.domain_event import DomainEvent
    from app.events.registry import EventRegistry

    # Make WidgetCreated a real DomainEvent subclass at runtime.
    event_cls = type("WidgetCreatedEvent", (WidgetCreated, DomainEvent), {})
    registry = EventRegistry()
    registry.register(event_cls)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # Enable RLS on event_store mirroring migration 0005.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE event_store ENABLE ROW LEVEL SECURITY"))
        conn.execute(text("ALTER TABLE event_store FORCE ROW LEVEL SECURITY"))
        conn.execute(
            text(
                f"""CREATE POLICY tenant_isolation ON event_store
                USING (tenant_id = current_setting('app.current_tenant', true)::uuid
                       OR current_setting('app.current_tenant', true)::uuid = '{NIL}'::uuid)
                WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid
                       OR current_setting('app.current_tenant', true)::uuid = '{NIL}'::uuid)"""
            )
        )

    captured: list[uuid.UUID] = []

    class WidgetProjection(BaseEventHandler):
        name = "widget-projection"
        event_types = frozenset({"WidgetCreated"})

        def handle(self, event, envelope, session):
            captured.append(event.widget_id)

    bus = InProcessEventBus()
    bus.register(WidgetProjection())

    # Seed a tenant to satisfy the FK.
    tenant_id = uuid.uuid4()
    with session_scope(PLATFORM_TENANT_ID) as s:
        s.execute(
            text(
                "INSERT INTO tenants (id, slug, name, status, isolation_mode, version, created_at, updated_at) "
                "VALUES (:id, :slug, :slug, 'active', 'shared', 1, now(), now())"
            ),
            {"id": str(tenant_id), "slug": f"t-{tenant_id.hex[:8]}"},
        )

    yield {
        "registry": registry, "event_cls": event_cls, "bus": bus,
        "tenant_id": tenant_id, "captured": captured, "engine": engine,
    }
    Base.metadata.drop_all(engine)


def _append(backbone, *, version: int, widget_id=None):
    from app.db.session import session_scope
    from app.events.envelope import EventEnvelope
    from app.repositories.event_store_repository import EventStoreRepository

    widget_id = widget_id or uuid.uuid4()
    ev = backbone["event_cls"](widget_id=widget_id, name="w")
    env = EventEnvelope.create(
        ev, tenant_id=backbone["tenant_id"], aggregate_id=widget_id,
        aggregate_version=version, aggregate_type="Widget",
    )
    with session_scope(backbone["tenant_id"]) as s:
        EventStoreRepository(s).append(env)
    return env


def test_append_writes_event_and_audit(backbone) -> None:
    from sqlalchemy import text
    from app.db.session import session_scope

    env = _append(backbone, version=1)
    with session_scope(backbone["tenant_id"]) as s:
        n_events = s.execute(text("SELECT count(*) FROM event_store")).scalar_one()
        n_audit = s.execute(
            text("SELECT count(*) FROM audit_log WHERE action='E' AND event_id=:e"),
            {"e": str(env.event_id)},
        ).scalar_one()
    assert n_events == 1 and n_audit == 1


def test_optimistic_concurrency_conflict(backbone) -> None:
    from app.events.exceptions import ConcurrencyConflictError

    wid = uuid.uuid4()
    _append(backbone, version=1, widget_id=wid)
    with pytest.raises(ConcurrencyConflictError):
        _append(backbone, version=1, widget_id=wid)  # same (aggregate_id, version)


def test_outbox_relay_dispatches_once_idempotently(backbone) -> None:
    from app.events.relay import run_outbox_relay

    _append(backbone, version=1)
    r1 = run_outbox_relay(bus=backbone["bus"])
    assert r1.published == 1 and len(backbone["captured"]) == 1
    # Second run: already published -> nothing re-delivered.
    r2 = run_outbox_relay(bus=backbone["bus"])
    assert r2.published == 0 and len(backbone["captured"]) == 1


def test_replay_by_aggregate_is_ordered(backbone) -> None:
    from app.db.session import session_scope
    from app.repositories.event_store_repository import EventStoreRepository

    wid = uuid.uuid4()
    for v in (1, 2, 3):
        _append(backbone, version=v, widget_id=wid)
    with session_scope(backbone["tenant_id"]) as s:
        rows = EventStoreRepository(s).replay_by_aggregate("Widget", wid)
        versions = [r.aggregate_version for r in rows]
    assert versions == [1, 2, 3]


def test_rls_isolates_event_store_across_tenants(backbone) -> None:
    from sqlalchemy import text
    from app.db.session import session_scope

    _append(backbone, version=1)  # tenant A
    other = uuid.uuid4()
    with session_scope(other) as s:
        visible = s.execute(text("SELECT count(*) FROM event_store")).scalar_one()
    assert visible == 0, "another tenant must not see tenant A's events"
