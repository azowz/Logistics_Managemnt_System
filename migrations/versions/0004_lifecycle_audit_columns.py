"""Lifecycle / audit / optimistic-lock columns (docs/03 §0; M2 Step 0).

Completes the §0 column rollout that M1 deferred. Additive and safe: every new
column carries a server default (or is nullable) so existing rows backfill
without a staged nullable→NOT NULL dance.

Per aggregate (``tenants``, ``users``, ``drivers``, ``vehicles``, ``warehouses``,
``shipments``):
  * ``version``     int NOT NULL DEFAULT 1  — optimistic-lock counter (ADR-004;
    paired with SQLAlchemy ``version_id_col`` and the event store's
    ``aggregate_version``).
  * ``created_by`` / ``updated_by`` uuid NULL — actor lineage (audit layer 1).
  * ``deleted_at`` timestamptz NULL — soft delete (not on immutable tables).
Plus ``shipments.currency_code`` varchar(3) NOT NULL DEFAULT 'SAR' (+ ISO-4217
CHECK). The append-only ``shipment_tracking_events`` table is intentionally left
untouched (immutable: no version / soft-delete).

Revision ID: 0004_lifecycle_audit_columns
Revises: 0003_multi_tenancy_rls
Create Date: 2026-06-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_lifecycle_audit_columns"
down_revision: Union[str, None] = "0003_multi_tenancy_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)

# Mutable aggregates that gain version + actor + soft-delete columns.
AGGREGATES: tuple[str, ...] = (
    "tenants",
    "users",
    "drivers",
    "vehicles",
    "warehouses",
    "shipments",
)


def upgrade() -> None:
    for table in AGGREGATES:
        op.add_column(
            table,
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )
        op.add_column(table, sa.Column("created_by", UUID, nullable=True))
        op.add_column(table, sa.Column("updated_by", UUID, nullable=True))
        op.add_column(table, sa.Column("deleted_at", TS, nullable=True))

    # Multi-currency readiness on the priced aggregate (docs/03 §0).
    op.add_column(
        "shipments",
        sa.Column("currency_code", sa.String(3), nullable=False, server_default=sa.text("'SAR'")),
    )
    op.create_check_constraint(
        "ck_shipments_currency_code",
        "shipments",
        "currency_code ~ '^[A-Z]{3}$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_shipments_currency_code", "shipments", type_="check")
    op.drop_column("shipments", "currency_code")
    for table in reversed(AGGREGATES):
        op.drop_column(table, "deleted_at")
        op.drop_column(table, "updated_by")
        op.drop_column(table, "created_by")
        op.drop_column(table, "version")
