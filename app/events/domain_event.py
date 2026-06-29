"""The reusable Domain Event abstraction (M2).

A :class:`DomainEvent` is an immutable fact that something happened in the domain
(past tense, ``<Aggregate><PastTenseVerb>`` — e.g. ``ShipmentAssigned``). It
carries only the *business payload*; the surrounding metadata (ids, aggregate,
correlation/causation, actor, timestamps) lives in :class:`~app.events.envelope.EventEnvelope`.

Concrete events are ``@dataclass(frozen=True)`` subclasses that declare two
class attributes — ``event_type`` and ``event_version`` — and their payload
fields, e.g.::

    @dataclass(frozen=True, slots=True)
    class ShipmentAssigned(DomainEvent):
        event_type = "ShipmentAssigned"
        event_version = 1
        shipment_id: uuid.UUID
        driver_id: uuid.UUID
        vehicle_id: uuid.UUID | None

Subclasses get JSON-safe :meth:`DomainEvent.to_payload` / :meth:`from_payload`
for free (UUID/datetime/Enum aware), so payloads round-trip cleanly through the
``event_store.payload`` JSONB column.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import decimal
import enum
import uuid
from typing import Any, ClassVar, Mapping, get_type_hints


def to_jsonable(value: Any) -> Any:
    """Recursively convert a value into a JSON-serializable form.

    Handles the types that appear in domain payloads: ``uuid.UUID`` → ``str``,
    ``datetime``/``date`` → ISO-8601 ``str``, :class:`enum.Enum` → its value,
    :class:`decimal.Decimal` → ``str`` (lossless, JSON has no native decimal), and
    mappings/sequences recursively. Other values are returned unchanged (and are
    expected to already be JSON-native).
    """

    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Mapping):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def _coerce(value: Any, annotation: Any) -> Any:
    """Best-effort coercion of a JSON value back to a field's declared type.

    Only the reversible conversions performed by :func:`to_jsonable` are undone
    (``str`` → ``uuid.UUID`` / ``datetime``). ``Optional`` annotations and values
    that are already of the target type pass through unchanged.
    """

    if value is None:
        return None
    # Unwrap Optional[...] / Union[..., None] to the first concrete arg.
    args = getattr(annotation, "__args__", None)
    if args:
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        annotation = non_none[0] if non_none else annotation
    if annotation is uuid.UUID and isinstance(value, str):
        return uuid.UUID(value)
    if annotation is dt.datetime and isinstance(value, str):
        return dt.datetime.fromisoformat(value)
    if annotation is dt.date and isinstance(value, str):
        return dt.date.fromisoformat(value)
    return value


class DomainEvent:
    """Abstract base for immutable domain events.

    Subclasses MUST be frozen dataclasses and MUST set ``event_type`` (and SHOULD
    set ``event_version``, default ``1``). These are :class:`typing.ClassVar`
    markers, never dataclass fields, so they are excluded from the payload.
    """

    # Declared by subclasses; the canonical wire name and its schema version.
    event_type: ClassVar[str]
    event_version: ClassVar[int] = 1

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Enforce the contract early (at import) rather than at first emit.
        if not getattr(cls, "event_type", None):
            raise TypeError(f"{cls.__name__} must define a non-empty 'event_type' ClassVar")

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-safe business payload (dataclass fields only)."""
        if not dataclasses.is_dataclass(self):
            raise TypeError(f"{type(self).__name__} must be a @dataclass DomainEvent")
        return {
            f.name: to_jsonable(getattr(self, f.name))
            for f in dataclasses.fields(self)
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DomainEvent":
        """Reconstruct an event instance from a stored JSON payload."""
        if not dataclasses.is_dataclass(cls):
            raise TypeError(f"{cls.__name__} must be a @dataclass DomainEvent")
        hints = get_type_hints(cls)
        field_names = {f.name for f in dataclasses.fields(cls)}
        kwargs = {
            name: _coerce(payload.get(name), hints.get(name))
            for name in field_names
        }
        return cls(**kwargs)  # type: ignore[call-arg]


__all__ = ["DomainEvent", "to_jsonable"]
