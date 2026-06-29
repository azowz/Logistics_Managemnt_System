"""Equipment & Asset domain — Sprint 6 (context #15, ADR-008/009).

Additive: creates the ``equipment_categories``, ``equipment_models`` and
``equipment`` tables (tenant-scoped, RLS, soft-delete, audit, optimistic lock,
JSONB tags), and adds the FK from ``shipments.equipment_id`` → ``equipment.id``
(SET NULL) now that the aggregate exists. No existing data is modified.

PostgreSQL-specific operations (RLS, partial indexes, the cross-table FK) are
guarded by ``_is_postgres()``; SQLite test schemas are built from the ORM models
via ``create_all`` and are unaffected.

Revision ID: 0009_equipment_domain
Revises:     0008_shipment_domain
Create Date: 2026-06-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009_equipment_domain"
down_revision: Union[str, None] = "0008_shipment_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"

_NEW_TABLES = ("equipment", "equipment_models", "equipment_categories")


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _audit_cols() -> list:
    return [
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("deleted_by", UUID, nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    ]


def _enable_rls(table: str) -> None:
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


def upgrade() -> None:
    # ----- equipment_categories -----
    op.create_table(
        "equipment_categories",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", UUID, nullable=True),
        *_audit_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_equipment_categories"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_equipment_categories_tenant_id_tenants", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["equipment_categories.id"],
            name="fk_equipment_categories_parent_id_equipment_categories",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_equipment_categories_tenant_id_code"
        ),
    )
    op.create_index(
        "ix_equipment_categories_tenant_id", "equipment_categories", ["tenant_id"]
    )

    # ----- equipment_models -----
    op.create_table(
        "equipment_models",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("category_id", UUID, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("manufacturer", sa.String(128), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("model_year", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        *_audit_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_equipment_models"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_equipment_models_tenant_id_tenants", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["equipment_categories.id"],
            name="fk_equipment_models_category_id_equipment_categories",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_equipment_models_tenant_id_code"
        ),
    )
    op.create_index(
        "ix_equipment_models_tenant_id", "equipment_models", ["tenant_id"]
    )
    op.create_index(
        "ix_equipment_models_category_id", "equipment_models", ["category_id"]
    )

    # ----- equipment -----
    op.create_table(
        "equipment",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("equipment_code", sa.String(64), nullable=False),
        sa.Column("asset_tag", sa.String(64), nullable=False),
        sa.Column("category_id", UUID, nullable=False),
        sa.Column("model_id", UUID, nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("serial_number", sa.String(128), nullable=True),
        sa.Column("manufacturer", sa.String(128), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("ownership_type", sa.String(32), nullable=False, server_default="owned"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("availability_status", sa.String(32), nullable=False, server_default="available"),
        sa.Column("weight_kg", sa.Numeric(12, 2), nullable=True),
        sa.Column("length_m", sa.Numeric(10, 3), nullable=True),
        sa.Column("width_m", sa.Numeric(10, 3), nullable=True),
        sa.Column("height_m", sa.Numeric(10, 3), nullable=True),
        sa.Column("volume_m3", sa.Numeric(12, 3), nullable=True),
        sa.Column("requires_permit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_escort", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_special_handling", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hazardous", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("temperature_sensitive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("insurance_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("current_warehouse_id", UUID, nullable=True),
        sa.Column("current_location", sa.String(512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        *_audit_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_equipment"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_equipment_tenant_id_tenants", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["equipment_categories.id"],
            name="fk_equipment_category_id_equipment_categories", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["equipment_models.id"],
            name="fk_equipment_model_id_equipment_models", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_warehouse_id"], ["warehouses.id"],
            name="fk_equipment_current_warehouse_id_warehouses", ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id", "equipment_code", name="uq_equipment_tenant_id_equipment_code"
        ),
        sa.UniqueConstraint(
            "tenant_id", "asset_tag", name="uq_equipment_tenant_id_asset_tag"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'under_maintenance', 'reserved', "
            "'in_transit', 'decommissioned')",
            name="ck_equipment_status",
        ),
        sa.CheckConstraint(
            "availability_status IN ('available', 'reserved', 'unavailable', "
            "'assigned', 'maintenance')",
            name="ck_equipment_availability_status",
        ),
        sa.CheckConstraint(
            "ownership_type IN ('owned', 'leased', 'customer_owned', 'third_party')",
            name="ck_equipment_ownership_type",
        ),
        sa.CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="ck_equipment_weight_non_negative"),
        sa.CheckConstraint("length_m IS NULL OR length_m >= 0", name="ck_equipment_length_non_negative"),
        sa.CheckConstraint("width_m IS NULL OR width_m >= 0", name="ck_equipment_width_non_negative"),
        sa.CheckConstraint("height_m IS NULL OR height_m >= 0", name="ck_equipment_height_non_negative"),
        sa.CheckConstraint("volume_m3 IS NULL OR volume_m3 >= 0", name="ck_equipment_volume_non_negative"),
    )
    op.create_index("ix_equipment_tenant_id", "equipment", ["tenant_id"])
    op.create_index("ix_equipment_status", "equipment", ["status"])
    op.create_index("ix_equipment_availability_status", "equipment", ["availability_status"])
    op.create_index("ix_equipment_category_id", "equipment", ["category_id"])
    op.create_index("ix_equipment_model_id", "equipment", ["model_id"])
    op.create_index("ix_equipment_current_warehouse_id", "equipment", ["current_warehouse_id"])

    # ----- cross-table FK + RLS + partial serial uniqueness (PostgreSQL) -----
    if _is_postgres():
        op.create_foreign_key(
            "fk_shipments_equipment_id_equipment",
            "shipments",
            "equipment",
            ["equipment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "uq_equipment_tenant_id_serial_number",
            "equipment",
            ["tenant_id", "serial_number"],
            unique=True,
            postgresql_where=sa.text("serial_number IS NOT NULL AND deleted_at IS NULL"),
        )
        for table in _NEW_TABLES:
            _enable_rls(table)


def downgrade() -> None:
    if _is_postgres():
        for table in _NEW_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index("uq_equipment_tenant_id_serial_number", table_name="equipment")
        op.drop_constraint(
            "fk_shipments_equipment_id_equipment", "shipments", type_="foreignkey"
        )

    op.drop_index("ix_equipment_current_warehouse_id", table_name="equipment")
    op.drop_index("ix_equipment_model_id", table_name="equipment")
    op.drop_index("ix_equipment_category_id", table_name="equipment")
    op.drop_index("ix_equipment_availability_status", table_name="equipment")
    op.drop_index("ix_equipment_status", table_name="equipment")
    op.drop_index("ix_equipment_tenant_id", table_name="equipment")
    op.drop_table("equipment")

    op.drop_index("ix_equipment_models_category_id", table_name="equipment_models")
    op.drop_index("ix_equipment_models_tenant_id", table_name="equipment_models")
    op.drop_table("equipment_models")

    op.drop_index("ix_equipment_categories_tenant_id", table_name="equipment_categories")
    op.drop_table("equipment_categories")
