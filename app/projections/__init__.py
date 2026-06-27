"""Read-model projection infrastructure (M2).

Projections are :class:`~app.events.bus.EventHandler` consumers that fold the
event stream into denormalized read models (ADR-006). This package provides the
reusable engine — the :class:`Projection` base and the :class:`ProjectionRebuilder`
(rebuild a read model by replaying the log) — that the concrete shipment / driver
/ fleet / warehouse / analytics projections plug into with their milestones (M6).
"""

from __future__ import annotations

from app.projections.engine import Projection, ProjectionRebuilder

__all__ = ["Projection", "ProjectionRebuilder"]
