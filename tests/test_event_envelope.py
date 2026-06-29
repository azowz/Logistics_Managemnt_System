"""Unit tests for EventEnvelope: create, to_record, from_record round-trips.

These are fully DB-free: no SQLAlchemy session or Postgres required.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import timezone

from app.common.datetime import utcnow
from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope


@dataclasses.dataclass(frozen=True, slots=True)
class _OrderShipped(DomainEvent):
    event_type = "OrderShipped"
    event_version = 2
    order_id: uuid.UUID
    carrier: str


def _make_envelope(**overrides) -> EventEnvelope:
    tid = uuid.uuid4()
    agg_id = uuid.uuid4()
    ev = _OrderShipped(order_id=agg_id, carrier="DHL")
    base = dict(
        tenant_id=tid,
        aggregate_id=agg_id,
        aggregate_version=3,
        aggregate_type="Order",
        correlation_id=uuid.uuid4(),
        causation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        occurred_at=utcnow(),
        metadata={"source": "test"},
    )
    base.update(overrides)
    return EventEnvelope.create(ev, **base)


# ---- create() -----------------------------------------------------------

def test_create_assigns_uuidv7_event_id() -> None:
    env = _make_envelope()
    assert isinstance(env.event_id, uuid.UUID)
    # UUIDv7 — version nibble is 0x7.
    assert (env.event_id.int >> 76) & 0xF == 7


def test_create_copies_event_type_and_version() -> None:
    env = _make_envelope()
    assert env.event_type == "OrderShipped"
    assert env.event_version == 2


def test_create_sets_aggregate_fields() -> None:
    agg_id = uuid.uuid4()
    env = _make_envelope(aggregate_id=agg_id, aggregate_version=5, aggregate_type="Order")
    assert env.aggregate_id == agg_id
    assert env.aggregate_version == 5
    assert env.aggregate_type == "Order"


def test_create_payload_is_json_safe() -> None:
    env = _make_envelope()
    assert isinstance(env.payload["order_id"], str)
    assert env.payload["carrier"] == "DHL"


def test_create_defaults_aggregate_type_to_empty() -> None:
    tid = uuid.uuid4()
    ev = _OrderShipped(order_id=uuid.uuid4(), carrier="x")
    env = EventEnvelope.create(ev, tenant_id=tid, aggregate_id=ev.order_id, aggregate_version=1)
    assert env.aggregate_type == ""


def test_create_optional_fields_default_to_none() -> None:
    tid = uuid.uuid4()
    ev = _OrderShipped(order_id=uuid.uuid4(), carrier="x")
    env = EventEnvelope.create(ev, tenant_id=tid, aggregate_id=ev.order_id, aggregate_version=1)
    assert env.correlation_id is None
    assert env.causation_id is None
    assert env.user_id is None
    assert env.metadata is None


def test_create_occurred_at_is_timezone_aware() -> None:
    env = _make_envelope()
    assert env.occurred_at.tzinfo is not None


def test_create_accepts_explicit_occurred_at() -> None:
    from datetime import datetime
    t = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    env = _make_envelope(occurred_at=t)
    assert env.occurred_at == t


# ---- to_record() --------------------------------------------------------

def test_to_record_maps_metadata_key_correctly() -> None:
    """ORM attr is event_metadata, SQL column is metadata — to_record must use event_metadata."""
    env = _make_envelope()
    record = env.to_record()
    assert "event_metadata" in record
    assert "metadata" not in record  # the field name is aliased in the ORM
    assert record["event_metadata"] == {"source": "test"}


def test_to_record_includes_all_envelope_fields() -> None:
    env = _make_envelope()
    record = env.to_record()
    required = {
        "event_id", "tenant_id", "aggregate_type", "aggregate_id", "aggregate_version",
        "event_type", "event_version", "payload", "event_metadata",
        "correlation_id", "causation_id", "user_id", "occurred_at",
    }
    assert required.issubset(record.keys())


# ---- from_record() + round-trip ----------------------------------------

class _FakeRow:
    """Minimal fake of an EventStore ORM row for from_record() testing."""

    def __init__(self, env: EventEnvelope) -> None:
        self.event_id = env.event_id
        self.tenant_id = env.tenant_id
        self.aggregate_type = env.aggregate_type
        self.aggregate_id = env.aggregate_id
        self.aggregate_version = env.aggregate_version
        self.event_type = env.event_type
        self.event_version = env.event_version
        self.payload = dict(env.payload)
        self.occurred_at = env.occurred_at
        self.correlation_id = env.correlation_id
        self.causation_id = env.causation_id
        self.user_id = env.user_id
        self.event_metadata = env.metadata  # ORM attribute name


def test_from_record_round_trips_all_fields() -> None:
    env = _make_envelope()
    row = _FakeRow(env)
    restored = EventEnvelope.from_record(row)

    assert restored.event_id == env.event_id
    assert restored.tenant_id == env.tenant_id
    assert restored.aggregate_type == env.aggregate_type
    assert restored.aggregate_id == env.aggregate_id
    assert restored.aggregate_version == env.aggregate_version
    assert restored.event_type == env.event_type
    assert restored.event_version == env.event_version
    assert restored.payload == env.payload
    assert restored.occurred_at == env.occurred_at
    assert restored.correlation_id == env.correlation_id
    assert restored.causation_id == env.causation_id
    assert restored.user_id == env.user_id
    assert restored.metadata == env.metadata


def test_from_record_null_metadata_yields_none() -> None:
    env = _make_envelope(metadata=None)
    row = _FakeRow(env)
    row.event_metadata = None
    restored = EventEnvelope.from_record(row)
    assert restored.metadata is None


def test_envelope_is_immutable() -> None:
    env = _make_envelope()
    try:
        env.event_id = uuid.uuid4()  # type: ignore[misc]
        raised = False
    except (AttributeError, dataclasses.FrozenInstanceError):
        raised = True
    assert raised, "EventEnvelope must be frozen (immutable)"
