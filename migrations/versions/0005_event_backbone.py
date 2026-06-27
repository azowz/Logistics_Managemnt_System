"""Enterprise event backbone (M2): event_store, outbox, idempotency, DLQ, audit_log.

Creates the durable foundation for CQRS-lite + EDA (ADR-004/007, docs/03 §6-7,
docs/11 §6):

* ``event_store``         — append-only log + transactional outbox; per-aggregate
  ordering via ``UNIQUE(aggregate_id, aggregate_version)``; partial outbox index.
* ``processed_events``    — per-consumer idempotency ledger (infra).
* ``dead_letter_events``  — exhausted-retry events (tenant-scoped).
* ``outbox_relay_state``  — relay cursor/heartbeat (infra).
* ``audit_log``           — immutable audit (tenant-scoped).

Row-Level Security (ENABLE + FORCE + tenant-isolation policy, mirroring `0003`)
is applied to the tenant-scoped tables; the consumer-side infra tables carry no
tenant data and are not RLS-scoped. PostgreSQL-guarded. Additive; Alembic-safe.

> Append-only immutability grants (``INSERT``/``SELECT`` only) require the
> dedicated non-superuser role (docs/10 R-1) and are applied with the role
> migration, not here. ``event_store`` is intentionally non-partitioned (see the
> model docstring: a global per-aggregate-version unique is incompatible with
> native partitioning by ``occurred_at``).

Revision ID: 0005_event_backbone
Revises: 0004_lifecycle_audit_columns
Create Date: 2026-06-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_event_backbone"
down_revision: Union[str, None] = "0004_lifecycle_audit_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"

# Tenant-scoped event-backbone tables that receive RLS.
RLS_TABLES: tuple[str, ...] = ("event_store", "dead_letter_events", "audit_log")


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    # ---- event_store (append-only log + transactional outbox) -----------
    op.create_table(
        "event_store",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(150), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("correlation_id", UUID, nullable=True),
        sa.Column("causation_id", UUID, nullable=True),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("recorded_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("published_at", TS, nullable=True),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", TS, nullable=True),
        sa.PrimaryKeyConstraint("event_id", name="pk_event_store"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_event_store_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "aggregate_id", "aggregate_version",
            name="uq_event_store_aggregate_id_aggregate_version",
        ),
    )
    op.create_index(
        "ix_event_store_unpublished", "event_store", ["next_attempt_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        "ix_event_store_tenant_id_occurred_at", "event_store", ["tenant_id", "occurred_at"],
    )
    op.create_index(
        "ix_event_store_aggregate", "event_store",
        ["aggregate_type", "aggregate_id", "aggregate_version"],
    )
    op.create_index(
        "ix_event_store_tenant_id_event_type", "event_store", ["tenant_id", "event_type"],
    )

    # ---- processed_events (idempotency ledger; infra) ------------------
    op.create_table(
        "processed_events",
        sa.Column("consumer", sa.String(150), nullable=False),
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("processed_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("consumer", "event_id", name="pk_processed_events"),
    )

    # ---- dead_letter_events (exhausted retries; tenant-scoped) ---------
    op.create_table(
        "dead_letter_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("consumer", sa.String(150), nullable=False),
        sa.Column("event_type", sa.String(150), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_failed_at", TS, nullable=False),
        sa.Column("last_failed_at", TS, nullable=False),
        sa.Column("replayed_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_dead_letter_events"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_dead_letter_events_tenant_id_tenants", ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_dead_letter_events_event_id", "dead_letter_events", ["event_id"])
    op.create_index(
        "ix_dead_letter_events_tenant_id_last_failed_at",
        "dead_letter_events", ["tenant_id", "last_failed_at"],
    )

    # ---- outbox_relay_state (relay cursor/heartbeat; infra) -----------
    op.create_table(
        "outbox_relay_state",
        sa.Column("id", UUID, nullable=False),
        sa.Column("relay_name", sa.String(100), nullable=False),
        sa.Column("last_published_at", TS, nullable=True),
        sa.Column("last_run_at", TS, nullable=True),
        sa.Column("published_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_relay_state"),
        sa.UniqueConstraint("relay_name", name="uq_outbox_relay_state_relay_name"),
    )

    # ---- audit_log (immutable audit; tenant-scoped) -------------------
    op.create_table(
        "audit_log",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("table_name", sa.String(100), nullable=False),
        sa.Column("row_id", UUID, nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("old_row", JSONB, nullable=True),
        sa.Column("new_row", JSONB, nullable=True),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("event_id", UUID, nullable=True),
        sa.Column("txid", sa.BigInteger(), nullable=True),
        sa.Column("at", TS, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_audit_log_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("action IN ('I','U','D','E')", name="ck_audit_log_action"),
    )
    op.create_index(
        "ix_audit_log_tenant_table_row_at", "audit_log",
        ["tenant_id", "table_name", "row_id", "at"],
    )

    # ---- Row-Level Security on tenant-scoped tables (PostgreSQL only) --
    if _is_postgres():
        for table in RLS_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY tenant_isolation ON {table}
                  USING (
                    tenant_id = current_setting('app.current_tenant', true)::uuid
                    OR current_setting('app.current_tenant', true)::uuid = '{NIL}'::uuid
                  )
                  WITH CHECK (
                    tenant_id = current_setting('app.current_tenant', true)::uuid
                    OR current_setting('app.current_tenant', true)::uuid = '{NIL}'::uuid
                  )
                """
            )


def downgrade() -> None:
    if _is_postgres():
        for table in RLS_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_audit_log_tenant_table_row_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("outbox_relay_state")
    op.drop_index("ix_dead_letter_events_tenant_id_last_failed_at", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_event_id", table_name="dead_letter_events")
    op.drop_table("dead_letter_events")
    op.drop_table("processed_events")
    op.drop_index("ix_event_store_tenant_id_event_type", table_name="event_store")
    op.drop_index("ix_event_store_aggregate", table_name="event_store")
    op.drop_index("ix_event_store_tenant_id_occurred_at", table_name="event_store")
    op.drop_index("ix_event_store_unpublished", table_name="event_store")
    op.drop_table("event_store")
