"""Metadata-level checks for the event-backbone + §0 model changes (no DB)."""

from __future__ import annotations

from sqlalchemy import UniqueConstraint, inspect

from app.db.base import Base

# Register models on metadata.
import app.models.tenant  # noqa: F401
import app.models.user  # noqa: F401
import app.models.driver  # noqa: F401
import app.models.vehicle  # noqa: F401
import app.models.warehouse  # noqa: F401
import app.models.shipment  # noqa: F401
import app.models.shipment_tracking_event  # noqa: F401
import app.models.event_store  # noqa: F401
import app.models.audit_log  # noqa: F401
from app.models.event_store import EventStore


def _md():
    return Base.metadata


def test_backbone_tables_exist() -> None:
    for t in ("event_store", "processed_events", "dead_letter_events", "outbox_relay_state", "audit_log"):
        assert t in _md().tables, f"missing {t}"


def test_event_store_concurrency_unique_and_metadata_column() -> None:
    es = _md().tables["event_store"]
    uniques = {
        tuple(c.name for c in u.columns)
        for u in es.constraints
        if isinstance(u, UniqueConstraint)
    }
    assert ("aggregate_id", "aggregate_version") in uniques
    # 'metadata' is reserved by SQLAlchemy; ORM attr is event_metadata -> column "metadata".
    assert "metadata" in es.columns
    assert EventStore.event_metadata.property.columns[0].name == "metadata"


def test_processed_events_composite_pk() -> None:
    pk = [c.name for c in _md().tables["processed_events"].primary_key]
    assert pk == ["consumer", "event_id"]


def test_audit_log_action_check_present() -> None:
    cks = [c.name for c in _md().tables["audit_log"].constraints if c.name]
    assert "ck_audit_log_action" in cks


def test_aggregates_have_optimistic_version() -> None:
    import app.models.tenant as t
    import app.models.user as u
    import app.models.shipment as s
    for cls in (t.Tenant, u.User, s.Shipment):
        assert inspect(cls).version_id_col is not None, f"{cls.__name__} missing version_id_col"
