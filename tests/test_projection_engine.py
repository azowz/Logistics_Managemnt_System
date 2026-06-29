"""Unit tests for the Projection base and ProjectionRebuilder (DB-free).

The rebuilder uses a fake session + fake repo so these tests run without a
database while still exercising the full rebuild + filter + SAVEPOINT loop.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Optional
from unittest.mock import MagicMock, call

import pytest

from app.events.bus import BaseEventHandler
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.events.registry import EventRegistry
from app.projections.engine import Projection, ProjectionRebuilder


# ---- test domain events -------------------------------------------------

@dataclasses.dataclass(frozen=True, slots=True)
class _WidgetCreated(DomainEvent):
    event_type = "WidgetCreated"
    event_version = 1
    widget_id: uuid.UUID


@dataclasses.dataclass(frozen=True, slots=True)
class _WidgetDeleted(DomainEvent):
    event_type = "WidgetDeleted"
    event_version = 1
    widget_id: uuid.UUID


# ---- fake infrastructure ------------------------------------------------

class _FakeNestedCtx:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _FakeSession:
    def begin_nested(self):
        return _FakeNestedCtx()


class _FakeRow:
    """Minimal EventStore-like object that EventEnvelope.from_record() can read."""

    def __init__(self, event: DomainEvent, tenant_id: uuid.UUID, agg_id: uuid.UUID, version: int) -> None:
        from app.events.envelope import EventEnvelope
        from app.common.datetime import utcnow

        env = EventEnvelope.create(
            event,
            tenant_id=tenant_id,
            aggregate_id=agg_id,
            aggregate_version=version,
            aggregate_type=type(event).event_type.replace("Widget", "Widget"),
        )
        self.event_id = env.event_id
        self.tenant_id = env.tenant_id
        self.aggregate_type = env.aggregate_type
        self.aggregate_id = env.aggregate_id
        self.aggregate_version = env.aggregate_version
        self.event_type = env.event_type
        self.event_version = env.event_version
        self.payload = env.payload
        self.occurred_at = env.occurred_at
        self.correlation_id = env.correlation_id
        self.causation_id = env.causation_id
        self.user_id = env.user_id
        self.event_metadata = env.metadata


# ---- concrete projection -------------------------------------------------

class _WidgetProjection(Projection):
    name = "widget-proj"
    event_types = frozenset({"WidgetCreated"})

    def __init__(self) -> None:
        self.applied: list[uuid.UUID] = []
        self.reset_count = 0

    def handle(self, event: DomainEvent, envelope: EventEnvelope, session) -> None:
        self.applied.append(event.widget_id)  # type: ignore[attr-defined]

    def reset(self, session, tenant_id: Optional[uuid.UUID] = None) -> None:
        self.applied.clear()
        self.reset_count += 1


# ---- Projection abstract API tests --------------------------------------

def test_projection_is_event_handler() -> None:
    proj = _WidgetProjection()
    assert proj.handles("WidgetCreated")
    assert not proj.handles("WidgetDeleted")  # filtered by event_types


def test_projection_reset_required() -> None:
    """Concrete projections must implement reset(); abstract raises."""

    class _BadProjection(Projection):
        name = "bad"

        def handle(self, event, envelope, session) -> None:
            pass

        # reset not implemented → abstract base raises NotImplementedError

    # An abstract ``reset`` makes the subclass non-instantiable (TypeError);
    # a concrete-but-unimplemented one would raise NotImplementedError on call.
    with pytest.raises((NotImplementedError, TypeError)):
        p = _BadProjection()
        p.reset(None)  # type: ignore[arg-type]


# ---- ProjectionRebuilder unit tests --------------------------------------

def _rebuild_env(tenant_id: uuid.UUID) -> tuple[EventRegistry, list[_FakeRow]]:
    """Build a registry and a fake event stream."""
    reg = EventRegistry()
    reg.register(_WidgetCreated)
    reg.register(_WidgetDeleted)

    agg_id = uuid.uuid4()
    rows = [
        _FakeRow(_WidgetCreated(widget_id=agg_id), tenant_id, agg_id, v)
        for v in range(1, 4)
    ] + [
        _FakeRow(_WidgetDeleted(widget_id=uuid.uuid4()), tenant_id, uuid.uuid4(), 1),
    ]
    return reg, rows


def test_rebuild_by_tenant_applies_only_matching_events() -> None:
    """ProjectionRebuilder must call handle() only for events the projection handles."""
    tenant_id = uuid.uuid4()
    reg, rows = _rebuild_env(tenant_id)

    fake_session = _FakeSession()

    class _FakeRepo:
        def replay_by_tenant(self, tid, **_):
            assert tid == tenant_id
            return rows

    # Monkey-patch session_scope to yield our fake_session.
    import contextlib
    from app import projections as proj_pkg
    import app.projections.engine as engine_mod

    @contextlib.contextmanager
    def _fake_scope(tid):
        yield fake_session

    original = engine_mod.session_scope
    engine_mod.session_scope = _fake_scope

    # Also patch EventStoreRepository inside the engine module.
    original_repo = engine_mod.EventStoreRepository
    engine_mod.EventStoreRepository = lambda s: _FakeRepo()

    try:
        projection = _WidgetProjection()
        rebuilder = ProjectionRebuilder(registry=reg)
        applied = rebuilder.rebuild_by_tenant(projection, tenant_id)
    finally:
        engine_mod.session_scope = original
        engine_mod.EventStoreRepository = original_repo

    # 3 WidgetCreated rows match; 1 WidgetDeleted does not (not in event_types).
    assert applied == 3
    assert len(projection.applied) == 3
    assert projection.reset_count == 1


def test_rebuild_by_tenant_calls_reset_before_applying_events() -> None:
    """reset() must be called once before any handle() during a full tenant rebuild."""
    tenant_id = uuid.uuid4()
    reg, rows = _rebuild_env(tenant_id)

    call_order: list[str] = []

    class _TrackingProjection(Projection):
        name = "tracking"
        event_types = frozenset({"WidgetCreated"})

        def handle(self, event, envelope, session) -> None:
            call_order.append("handle")

        def reset(self, session, tenant_id=None) -> None:
            call_order.append("reset")

    fake_session = _FakeSession()

    class _FakeRepo:
        def replay_by_tenant(self, tid, **_):
            return rows

    import contextlib
    import app.projections.engine as engine_mod

    @contextlib.contextmanager
    def _fake_scope(tid):
        yield fake_session

    original = engine_mod.session_scope
    engine_mod.session_scope = _fake_scope
    original_repo = engine_mod.EventStoreRepository
    engine_mod.EventStoreRepository = lambda s: _FakeRepo()

    try:
        rebuilder = ProjectionRebuilder(registry=reg)
        rebuilder.rebuild_by_tenant(_TrackingProjection(), tenant_id)
    finally:
        engine_mod.session_scope = original
        engine_mod.EventStoreRepository = original_repo

    assert call_order[0] == "reset", "reset must be called before the first handle"
    assert call_order.count("reset") == 1


def test_rebuild_by_aggregate_skips_unmatched_events() -> None:
    """Aggregate-scoped rebuild applies only events the projection handles."""
    tenant_id = uuid.uuid4()
    agg_id = uuid.uuid4()

    reg = EventRegistry()
    reg.register(_WidgetCreated)
    reg.register(_WidgetDeleted)

    rows = [
        _FakeRow(_WidgetCreated(widget_id=agg_id), tenant_id, agg_id, 1),
        _FakeRow(_WidgetDeleted(widget_id=agg_id), tenant_id, agg_id, 2),
    ]

    fake_session = _FakeSession()

    class _FakeRepo:
        def replay_by_aggregate(self, agg_type, agg_id_arg):
            return rows

    import contextlib
    import app.projections.engine as engine_mod

    @contextlib.contextmanager
    def _fake_scope(tid):
        yield fake_session

    original = engine_mod.session_scope
    engine_mod.session_scope = _fake_scope
    original_repo = engine_mod.EventStoreRepository
    engine_mod.EventStoreRepository = lambda s: _FakeRepo()

    try:
        projection = _WidgetProjection()  # handles only WidgetCreated
        rebuilder = ProjectionRebuilder(registry=reg)
        applied = rebuilder.rebuild_by_aggregate(projection, tenant_id, "Widget", agg_id)
    finally:
        engine_mod.session_scope = original
        engine_mod.EventStoreRepository = original_repo

    assert applied == 1  # only WidgetCreated matches
    assert len(projection.applied) == 1
