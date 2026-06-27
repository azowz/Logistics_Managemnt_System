"""Unit tests for the DomainEvent abstraction (serialization round-trip)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import uuid

from app.events.domain_event import DomainEvent, to_jsonable


class _Priority(str, enum.Enum):
    LOW = "low"
    HIGH = "high"


@dataclasses.dataclass(frozen=True, slots=True)
class _SampleEvent(DomainEvent):
    event_type = "SampleHappened"
    event_version = 1
    entity_id: uuid.UUID
    when: dt.datetime
    priority: _Priority
    note: str | None


def test_to_payload_is_json_safe() -> None:
    eid = uuid.uuid4()
    now = dt.datetime(2026, 6, 22, 12, 0, tzinfo=dt.timezone.utc)
    ev = _SampleEvent(entity_id=eid, when=now, priority=_Priority.HIGH, note=None)
    payload = ev.to_payload()
    assert payload == {
        "entity_id": str(eid),
        "when": now.isoformat(),
        "priority": "high",
        "note": None,
    }
    # event_type / event_version are ClassVars, never part of the payload.
    assert "event_type" not in payload and "event_version" not in payload


def test_from_payload_coerces_back_to_field_types() -> None:
    eid = uuid.uuid4()
    now = dt.datetime(2026, 6, 22, 12, 0, tzinfo=dt.timezone.utc)
    ev = _SampleEvent(entity_id=eid, when=now, priority=_Priority.LOW, note="x")
    restored = _SampleEvent.from_payload(ev.to_payload())
    assert restored.entity_id == eid and isinstance(restored.entity_id, uuid.UUID)
    assert restored.when == now and isinstance(restored.when, dt.datetime)
    assert restored.note == "x"


def test_to_jsonable_handles_nested_structures() -> None:
    eid = uuid.uuid4()
    value = {"ids": [eid], "meta": {"p": _Priority.HIGH}}
    assert to_jsonable(value) == {"ids": [str(eid)], "meta": {"p": "high"}}


def test_event_type_is_required() -> None:
    try:

        @dataclasses.dataclass(frozen=True)
        class _Bad(DomainEvent):  # no event_type
            x: int

        raised = False
    except TypeError:
        raised = True
    assert raised, "DomainEvent subclass without event_type must raise"
