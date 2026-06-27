"""Event-type registry and version upcasting (M2).

The registry maps a canonical ``event_type`` (and version) to the concrete
:class:`~app.events.domain_event.DomainEvent` subclass that represents it, and
holds the **upcasters** that migrate an old event version's payload forward to
the current version. This is how the platform evolves events without breaking
history (the M2 "event versioning / upcasting" requirement):

    v1 payload --upcaster(1→2)--> v2 payload --upcaster(2→3)--> ... --> current

Deserialization always upcasts to the current version before instantiating the
current class, so consumers/projections only ever see the latest shape.

A process-wide :data:`event_registry` instance is provided; contexts register
their events at import time via the :func:`register_event` decorator.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from app.events.domain_event import DomainEvent
from app.events.envelope import EventEnvelope
from app.events.exceptions import EventDeserializationError, UnknownEventTypeError
from app.observability.logging import get_logger

logger = get_logger(__name__)

# An upcaster transforms a payload from one event version to the next.
Upcaster = Callable[[Mapping[str, Any]], dict[str, Any]]


class EventRegistry:
    """A registry of event classes by ``event_type`` + version, with upcasters."""

    def __init__(self) -> None:
        # event_type -> {version: DomainEvent subclass}
        self._classes: dict[str, dict[int, type[DomainEvent]]] = {}
        # event_type -> highest registered version (the "current" shape)
        self._current: dict[str, int] = {}
        # (event_type, from_version) -> upcaster producing the next version payload
        self._upcasters: dict[tuple[str, int], Upcaster] = {}

    # ---- registration --------------------------------------------------
    def register(self, event_cls: type[DomainEvent]) -> type[DomainEvent]:
        """Register a concrete event class under its ``event_type``/``event_version``."""
        etype = event_cls.event_type
        eversion = event_cls.event_version
        versions = self._classes.setdefault(etype, {})
        if eversion in versions and versions[eversion] is not event_cls:
            raise ValueError(
                f"Event {etype} v{eversion} already registered as {versions[eversion].__name__}"
            )
        versions[eversion] = event_cls
        self._current[etype] = max(self._current.get(etype, 0), eversion)
        logger.debug("Registered event", event_type=etype, version=eversion)
        return event_cls

    def register_upcaster(self, event_type: str, from_version: int, upcaster: Upcaster) -> None:
        """Register an upcaster migrating ``from_version`` → ``from_version + 1``."""
        self._upcasters[(event_type, from_version)] = upcaster
        logger.debug("Registered upcaster", event_type=event_type, from_version=from_version)

    # ---- lookup --------------------------------------------------------
    def current_version(self, event_type: str) -> Optional[int]:
        """Return the highest registered version for ``event_type`` (or ``None``)."""
        return self._current.get(event_type)

    def get(self, event_type: str, version: int) -> Optional[type[DomainEvent]]:
        """Return the registered class for an exact ``event_type``/``version``."""
        return self._classes.get(event_type, {}).get(version)

    def is_registered(self, event_type: str) -> bool:
        return event_type in self._classes

    # ---- upcasting + deserialization -----------------------------------
    def upcast(self, event_type: str, version: int, payload: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        """Apply the upcaster chain, returning ``(current_version, payload)``.

        Missing intermediate upcasters raise :class:`EventDeserializationError`
        so a gap is loud rather than silently delivering a stale shape.
        """
        target = self._current.get(event_type)
        if target is None:
            raise UnknownEventTypeError(f"No registered class for event_type={event_type!r}")
        current_payload = dict(payload)
        v = version
        while v < target:
            upcaster = self._upcasters.get((event_type, v))
            if upcaster is None:
                raise EventDeserializationError(
                    f"Missing upcaster {event_type} v{v}->v{v + 1} (target v{target})"
                )
            current_payload = dict(upcaster(current_payload))
            v += 1
        return target, current_payload

    def deserialize(self, envelope: EventEnvelope) -> DomainEvent:
        """Reconstruct the current-version :class:`DomainEvent` from an envelope."""
        target_version, payload = self.upcast(
            envelope.event_type, envelope.event_version, envelope.payload
        )
        event_cls = self.get(envelope.event_type, target_version)
        if event_cls is None:  # pragma: no cover - guarded by upcast()
            raise UnknownEventTypeError(
                f"No class for {envelope.event_type} v{target_version}"
            )
        try:
            return event_cls.from_payload(payload)
        except Exception as exc:  # noqa: BLE001 - normalize to a typed error
            raise EventDeserializationError(
                f"Failed to deserialize {envelope.event_type} v{target_version}: {exc}"
            ) from exc


# Process-wide registry; contexts register their events at import time.
event_registry = EventRegistry()


def register_event(event_cls: type[DomainEvent]) -> type[DomainEvent]:
    """Class decorator registering an event on the process-wide registry."""
    return event_registry.register(event_cls)


__all__ = ["EventRegistry", "Upcaster", "event_registry", "register_event"]
