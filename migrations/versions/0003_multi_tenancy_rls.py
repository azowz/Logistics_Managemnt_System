"""Multi-tenancy + Row-Level Security (Phase 5 milestone M1, ADR-001 / docs/03 §8).

Additive, staged, and PostgreSQL-targeted. Steps:
  1. Create ``tenants`` and seed the nil-UUID platform tenant ("tenant 0").
  2. For every aggregate: add ``tenant_id`` nullable -> backfill to platform ->
     set NOT NULL -> add FK(RESTRICT) -> add tenant-leading index.
  3. Swap single-column unique keys for per-tenant composites (docs/03 §3.2).
  4. Enable + FORCE Row-Level Security with a tenant-isolation policy on every
     tenant table (the platform nil-UUID GUC sees all; an unset GUC sees none).

RLS is PostgreSQL-only and is guarded by the active dialect so an offline render
for another backend simply omits it. Hand-authored (the project hand-authors
migrations; constraint names follow app/db/base.py NAMING_CONVENTION).

Revision ID: 0003_multi_tenancy_rls
Revises: 0002_shipment_offer_fields
Create Date: 2026-06-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_multi_tenancy_rls"
down_revision: Union[str, None] = "0002_shipment_offer_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)

NIL = "00000000-0000-0000-0000-000000000000"

# Aggregate tables that gain tenant_id + RLS (order respects FK dependencies).
TENANT_TABLES: tuple[str, ...] = (
    "users",
    "warehouses",
    "drivers",
    "vehicles",
    "shipments",
    "shipment_tracking_events",
)

# Old single-column unique keys -> (table, [(constraint_name)]) to drop.
OLD_UNIQUES: tuple[tuple[str, str], ...] = (
    ("users", "uq_users_email"),
    ("warehouses", "uq_warehouses_code"),
    ("drivers", "uq_drivers_user_id"),
    ("drivers", "uq_drivers_license_number"),
    ("vehicles", "uq_vehicles_plate_number"),
    ("vehicles", "uq_vehicles_vin"),
    ("shipments", "uq_shipments_reference_code"),
)

# New per-tenant composite uniques: (constraint_name, table, [columns]).
NEW_UNIQUES: tuple[tuple[str, str, list[str]], ...] = (
    ("uq_users_tenant_id_email", "users", ["tenant_id", "email"]),
    ("uq_warehouses_tenant_id_code", "warehouses", ["tenant_id", "code"]),
    ("uq_drivers_tenant_id_user_id", "drivers", ["tenant_id", "user_id"]),
    ("uq_drivers_tenant_id_license_number", "drivers", ["tenant_id", "license_number"]),
    ("uq_vehicles_tenant_id_plate_number", "vehicles", ["tenant_id", "plate_number"]),
    ("uq_vehicles_tenant_id_vin", "vehicles", ["tenant_id", "vin"]),
    ("uq_shipments_tenant_id_reference_code", "shipments", ["tenant_id", "reference_code"]),
)


def _is_postgres() -> bool:
    """True when the migration runs (or renders) against PostgreSQL."""
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    # ---- 1. tenants + platform seed -------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", UUID, nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("isolation_mode", sa.String(32), nullable=False, server_default="shared"),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("settings", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_tenants_status"),
        sa.CheckConstraint(
            "isolation_mode IN ('shared', 'dedicated')",
            name="ck_tenants_isolation_mode",
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO tenants (id, slug, name, status, isolation_mode, created_at, updated_at) "
            "VALUES (:id, 'platform', 'Platform', 'active', 'shared', now(), now())"
        ).bindparams(id=NIL)
    )

    # ---- 2. tenant_id on every aggregate (staged, zero-downtime) ---------
    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("tenant_id", UUID, nullable=True))
        op.execute(
            sa.text(f"UPDATE {table} SET tenant_id = :id WHERE tenant_id IS NULL").bindparams(id=NIL)
        )
        op.alter_column(table, "tenant_id", existing_type=UUID, nullable=False)
        op.create_foreign_key(
            f"fk_{table}_tenant_id_tenants",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # ---- 3. swap single-column uniques for per-tenant composites ---------
    # users.email also had a UNIQUE index from baseline; replace it with a
    # plain (non-unique) lookup index, since uniqueness is now per tenant.
    op.drop_index("ix_users_email", table_name="users")
    for table, name in OLD_UNIQUES:
        op.drop_constraint(name, table, type_="unique")
    for name, table, cols in NEW_UNIQUES:
        op.create_unique_constraint(name, table, cols)
    op.create_index("ix_users_email", "users", ["email"])  # non-unique lookup

    # ---- 4. Row-Level Security (PostgreSQL only) ------------------------
    if _is_postgres():
        for table in TENANT_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            # FORCE so even the table owner is subject to the policy, making the
            # isolation gate meaningful regardless of the connecting role.
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
    # ---- 4. drop RLS ----------------------------------------------------
    if _is_postgres():
        for table in TENANT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # ---- 3. restore single-column uniques -------------------------------
    op.drop_index("ix_users_email", table_name="users")
    for name, table, _cols in NEW_UNIQUES:
        op.drop_constraint(name, table, type_="unique")
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_unique_constraint("uq_warehouses_code", "warehouses", ["code"])
    op.create_unique_constraint("uq_drivers_user_id", "drivers", ["user_id"])
    op.create_unique_constraint("uq_drivers_license_number", "drivers", ["license_number"])
    op.create_unique_constraint("uq_vehicles_plate_number", "vehicles", ["plate_number"])
    op.create_unique_constraint("uq_vehicles_vin", "vehicles", ["vin"])
    op.create_unique_constraint("uq_shipments_reference_code", "shipments", ["reference_code"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- 2. drop tenant_id from aggregates ------------------------------
    for table in reversed(TENANT_TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id_tenants", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    # ---- 1. drop tenants ------------------------------------------------
    op.drop_table("tenants")
