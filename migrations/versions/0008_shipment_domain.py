"""Shipment domain refactor — Sprint 5 (additive, backward-compatible).

Aligns the pre-existing ``shipments`` table with the production-grade domain
pattern established by Customer (Sprint 3) and Order (Sprint 4):

  * New nullable columns: ``order_id`` (FK orders SET NULL), ``cargo_description``,
    ``equipment_id``, ``picked_up_at``, ``failed_at``, ``return_reason``,
    ``deleted_by``.
  * New ``priority`` column (NOT NULL, default 'normal') + value CHECK.
  * Indexes for the operational access paths (status, priority, order_id,
    driver_id, vehicle_id, delivery_due_at) and partial indexes for the
    active driver/vehicle assignment and ready-offer queries (PostgreSQL only).

All operations are additive and safe: every new column is nullable or carries a
server default, so existing rows backfill without a staged migration. The
``status`` column is a plain VARCHAR (SQLAlchemy ``Enum(create_constraint=False)``),
so the new ``picked_up`` / ``delayed`` states require no constraint change.
Row-Level Security is already enabled on ``shipments`` (migration 0003).

Revision ID: 0008_shipment_domain
Revises:     0007_order_domain
Create Date: 2026-06-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_shipment_domain"
down_revision: Union[str, None] = "0007_order_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    # --- additive columns ---------------------------------------------------
    op.add_column("shipments", sa.Column("order_id", UUID, nullable=True))
    op.add_column(
        "shipments",
        sa.Column("priority", sa.String(32), nullable=False, server_default="normal"),
    )
    op.add_column("shipments", sa.Column("cargo_description", sa.Text(), nullable=True))
    op.add_column("shipments", sa.Column("equipment_id", UUID, nullable=True))
    op.add_column("shipments", sa.Column("picked_up_at", TS, nullable=True))
    op.add_column("shipments", sa.Column("failed_at", TS, nullable=True))
    op.add_column("shipments", sa.Column("return_reason", sa.String(255), nullable=True))
    op.add_column("shipments", sa.Column("deleted_by", UUID, nullable=True))

    # --- value constraint mirroring the model -------------------------------
    op.create_check_constraint(
        "ck_shipments_priority",
        "shipments",
        "priority IN ('low', 'normal', 'high', 'urgent')",
    )

    # --- order linkage (PostgreSQL FK; SQLite has no ALTER ADD CONSTRAINT) ---
    if _is_postgres():
        op.create_foreign_key(
            "fk_shipments_order_id_orders",
            "shipments",
            "orders",
            ["order_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # --- indexes for operational access paths -------------------------------
    op.create_index("ix_shipments_order_id", "shipments", ["order_id"])
    op.create_index("ix_shipments_status", "shipments", ["status"])
    op.create_index("ix_shipments_priority", "shipments", ["priority"])
    op.create_index("ix_shipments_driver_id", "shipments", ["driver_id"])
    op.create_index("ix_shipments_vehicle_id", "shipments", ["vehicle_id"])
    op.create_index("ix_shipments_delivery_due_at", "shipments", ["delivery_due_at"])

    # --- partial indexes (PostgreSQL only) ----------------------------------
    if _is_postgres():
        # Ready offers awaiting a driver (driver_self.list_nearby_offers).
        op.create_index(
            "ix_shipments_ready_unassigned",
            "shipments",
            ["tenant_id"],
            postgresql_where=sa.text("status = 'READY' AND driver_id IS NULL"),
        )
        # Active driver assignment exclusivity guard.
        op.create_index(
            "ix_shipments_active_driver",
            "shipments",
            ["driver_id"],
            postgresql_where=sa.text(
                "status IN ('ASSIGNED', 'PICKED_UP', 'IN_TRANSIT', 'DELAYED') "
                "AND deleted_at IS NULL"
            ),
        )
        # Active vehicle assignment exclusivity guard.
        op.create_index(
            "ix_shipments_active_vehicle",
            "shipments",
            ["vehicle_id"],
            postgresql_where=sa.text(
                "status IN ('ASSIGNED', 'PICKED_UP', 'IN_TRANSIT', 'DELAYED') "
                "AND deleted_at IS NULL"
            ),
        )


def downgrade() -> None:
    if _is_postgres():
        op.drop_index("ix_shipments_active_vehicle", table_name="shipments")
        op.drop_index("ix_shipments_active_driver", table_name="shipments")
        op.drop_index("ix_shipments_ready_unassigned", table_name="shipments")

    op.drop_index("ix_shipments_delivery_due_at", table_name="shipments")
    op.drop_index("ix_shipments_vehicle_id", table_name="shipments")
    op.drop_index("ix_shipments_driver_id", table_name="shipments")
    op.drop_index("ix_shipments_priority", table_name="shipments")
    op.drop_index("ix_shipments_status", table_name="shipments")
    op.drop_index("ix_shipments_order_id", table_name="shipments")

    if _is_postgres():
        op.drop_constraint("fk_shipments_order_id_orders", "shipments", type_="foreignkey")

    op.drop_constraint("ck_shipments_priority", "shipments", type_="check")

    op.drop_column("shipments", "deleted_by")
    op.drop_column("shipments", "return_reason")
    op.drop_column("shipments", "failed_at")
    op.drop_column("shipments", "picked_up_at")
    op.drop_column("shipments", "equipment_id")
    op.drop_column("shipments", "cargo_description")
    op.drop_column("shipments", "priority")
    op.drop_column("shipments", "order_id")
