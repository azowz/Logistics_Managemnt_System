"""Order domain — Sprint 4.

Creates the ``orders`` table with:
  * Full transport-order columns (classification, scheduling, locations, cargo).
  * Tenant-scoped uniqueness for ``order_number``.
  * ``status`` / ``order_type`` / ``order_source`` / ``priority`` CHECK constraints.
  * Non-negative CHECKs for cargo weight/volume and distance.
  * FKs to tenants (RESTRICT), customers (RESTRICT), users (SET NULL dispatcher).
  * Soft-delete (``deleted_at``, ``deleted_by``), audit, timestamps.
  * Optimistic concurrency (``version``).
  * Row-Level Security (PostgreSQL only; mirrors migration 0003 / 0006).

Revision ID: 0007_order_domain
Revises:     0006_customer_domain
Create Date: 2026-06-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_order_domain"
down_revision: Union[str, None] = "0006_customer_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "orders",
        # --- identity ---
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("order_number", sa.String(64), nullable=False),

        # --- classification ---
        sa.Column("order_type", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("order_source", sa.String(32), nullable=False, server_default="web"),
        sa.Column("priority", sa.String(32), nullable=False, server_default="normal"),

        # --- lifecycle state ---
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),

        # --- scheduling ---
        sa.Column("requested_pickup_date", TS, nullable=True),
        sa.Column("requested_delivery_date", TS, nullable=True),

        # --- locations ---
        sa.Column("pickup_location", sa.Text(), nullable=True),
        sa.Column("delivery_location", sa.Text(), nullable=True),
        sa.Column("pickup_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("pickup_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("delivery_latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("delivery_longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("distance_km", sa.Numeric(10, 2), nullable=True),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True),

        # --- cargo ---
        sa.Column("cargo_description", sa.Text(), nullable=True),
        sa.Column("cargo_weight_kg", sa.Numeric(12, 2), nullable=True),
        sa.Column("cargo_volume_m3", sa.Numeric(12, 3), nullable=True),
        sa.Column("dangerous_goods", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("temperature_requirements", sa.String(128), nullable=True),
        sa.Column("is_fragile", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("insurance_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),

        # --- instructions ---
        sa.Column("special_instructions", sa.Text(), nullable=True),

        # --- assignment ---
        sa.Column("assigned_dispatcher_id", UUID, nullable=True),

        # --- lifecycle timestamps / reasons ---
        sa.Column("submitted_at", TS, nullable=True),
        sa.Column("approved_at", TS, nullable=True),
        sa.Column("scheduled_at", TS, nullable=True),
        sa.Column("assigned_at", TS, nullable=True),
        sa.Column("picked_up_at", TS, nullable=True),
        sa.Column("delivered_at", TS, nullable=True),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("failed_at", TS, nullable=True),
        sa.Column("cancellation_reason", sa.String(512), nullable=True),
        sa.Column("failure_reason", sa.String(512), nullable=True),

        # --- timestamps (TimestampMixin) ---
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),

        # --- audit (AuditMixin) ---
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),

        # --- soft-delete (SoftDeleteMixin + extension) ---
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("deleted_by", UUID, nullable=True),

        # --- optimistic lock (ADR-004) ---
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),

        # --- constraints ---
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_orders_tenant_id_tenants", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"],
            name="fk_orders_customer_id_customers", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_dispatcher_id"], ["users.id"],
            name="fk_orders_assigned_dispatcher_id_users", ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id", "order_number", name="uq_orders_tenant_id_order_number"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'scheduled', "
            "'assigned', 'in_transit', 'delivered', 'cancelled', 'failed')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint(
            "order_type IN ('standard', 'express', 'same_day', 'economy', 'return')",
            name="ck_orders_order_type",
        ),
        sa.CheckConstraint(
            "order_source IN ('web', 'mobile', 'api', 'phone', 'email', 'walk_in')",
            name="ck_orders_order_source",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_orders_priority",
        ),
        sa.CheckConstraint(
            "cargo_weight_kg IS NULL OR cargo_weight_kg >= 0",
            name="ck_orders_cargo_weight_non_negative",
        ),
        sa.CheckConstraint(
            "cargo_volume_m3 IS NULL OR cargo_volume_m3 >= 0",
            name="ck_orders_cargo_volume_non_negative",
        ),
        sa.CheckConstraint(
            "distance_km IS NULL OR distance_km >= 0",
            name="ck_orders_distance_non_negative",
        ),
    )

    # --- indexes ---
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_priority", "orders", ["priority"])
    op.create_index("ix_orders_assigned_dispatcher_id", "orders", ["assigned_dispatcher_id"])

    # --- Row-Level Security (PostgreSQL only, mirrors migration 0003 / 0006) ---
    if _is_postgres():
        op.execute("ALTER TABLE orders ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE orders FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON orders
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
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON orders")
        op.execute("ALTER TABLE orders NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE orders DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_orders_assigned_dispatcher_id", table_name="orders")
    op.drop_index("ix_orders_priority", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_index("ix_orders_tenant_id", table_name="orders")
    op.drop_table("orders")
