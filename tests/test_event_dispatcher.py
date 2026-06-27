"""Unit tests for the idempotent dispatcher (retry, DLQ, savepoint isolation).

DB-free: a fake repository and a fake session stand in for persistence so the
dispatch policy is exercised on any backend.
"""

from __future__ import annotations

import dataclasses
import uuid

from app.events.bus import BaseEventHandler
from app.events.dispatcher import DEAD_LETTERED, PROCESSED, SKIPPED, Dispatcher
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.events.registry import EventRegistry


@dataclasses.dataclass(frozen=True, slots=True)
class _Pinged(DomainEvent):
    event_type = "Pinged"
    event_version = 1
    target_id: uuid.UUID


class _FakeNested:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False  # never suppress: handler errors propagate to the dispatcher


class _FakeSession:
    def begin_nested(self):
        return _FakeNested()


class _FakeRepo:
    def __init__(self) -> None:
        self.processed: set[tuple[str, uuid.UUID]] = set()
        self.dead: list[dict] = []

    def is_processed(self, consumer, event_id):
        return (consumer, event_id) in self.processed

    def mark_processed(self, consumer, event_id):
        self.processed.add((consumer, event_id))

    def add_dead_letter(self, **kwargs):
        self.dead.append(kwargs)


class _Handler(BaseEventHandler):
    name = "test-consumer"

    def __init__(self, *, fail_times: int = 0) -> None:
        self.calls = 0
        self._fail_times = fail_times

    def handle(self, event, envelope, session) -> None:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise RuntimeError(f"boom #{self.calls}")


def _registry() -> EventRegistry:
    reg = EventRegistry()
    reg.register(_Pinged)
    return reg


def _envelope() -> EventEnvelope:
    tid = uuid.uuid4()
    ev = _Pinged(target_id=uuid.uuid4())
    return EventEnvelope.create(ev, tenant_id=tid, aggregate_id=ev.target_id, aggregate_version=1, aggregate_type="Ping")


def _dispatcher(repo: _FakeRepo) -> Dispatcher:
    return Dispatcher(_FakeSession(), repo=repo, registry=_registry(), sleep=lambda *_: None)


def test_successful_dispatch_marks_processed() -> None:
    repo = _FakeRepo()
    handler = _Handler()
    env = _envelope()
    assert _dispatcher(repo).dispatch(handler, env) == PROCESSED
    assert handler.calls == 1
    assert (handler.name, env.event_id) in repo.processed


def test_already_processed_is_skipped() -> None:
    repo = _FakeRepo()
    handler = _Handler()
    env = _envelope()
    repo.processed.add((handler.name, env.event_id))
    assert _dispatcher(repo).dispatch(handler, env) == SKIPPED
    assert handler.calls == 0  # handler not invoked


def test_retries_then_succeeds() -> None:
    repo = _FakeRepo()
    handler = _Handler(fail_times=2)  # fails twice, succeeds on 3rd
    env = _envelope()
    assert _dispatcher(repo).dispatch(handler, env) == PROCESSED
    assert handler.calls == 3
    assert (handler.name, env.event_id) in repo.processed
    assert repo.dead == []


def test_exhausted_retries_dead_letters() -> None:
    repo = _FakeRepo()
    handler = _Handler(fail_times=99)  # always fails
    env = _envelope()
    assert _dispatcher(repo).dispatch(handler, env) == DEAD_LETTERED
    # default max_retries=3 -> 4 attempts total.
    assert handler.calls == 4
    assert len(repo.dead) == 1
    dl = repo.dead[0]
    assert dl["consumer"] == handler.name and dl["event_id"] == env.event_id
    # Dead-lettered events are marked processed so they are not redelivered.
    assert (handler.name, env.event_id) in repo.processed
