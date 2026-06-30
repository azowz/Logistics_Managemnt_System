"""Compliance & Permits domain — Sprint 7 (context #16, ADR-008).

Additive: creates ``permits``, ``escorts``, ``route_restrictions``,
``axle_weight_profiles``, ``compliance_checks``, ``operator_certifications`` —
tenant-scoped, RLS, soft-delete, audit, optimistic lock, JSONB fields. No
existing table is modified. PostgreSQL-specific operations (RLS) are guarded by
``_is_postgres()``; SQLite test schemas are built from the ORM via create_all.

Revision ID: 0010_compliance_permits_domain
Revises:     0009_equipment_domain
Create Date: 2026-06-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_compliance_permits_domain"
down_revision: Union[str, None] = "0009_equipment_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"

_TABLES = (
    "operator_certifications",
    "compliance_checks",
    "axle_weight_profiles",
    "escorts",
    "permits",
    "route_restrictions",
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _audit():
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
          USING (tenant_id = current_setting('app.current_tenant', true)::uuid
                 OR current_setting('app.current_tenant', true)::uuid = '{NIL}'::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid
                 OR current_setting('app.current_tenant', true)::uuid = '{NIL}'::uuid)
        """
    )


def upgrade() -> None:
    # ----- route_restrictions -----
    op.create_table(
        "route_restrictions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("region", sa.String(128), nullable=True),
        sa.Column("road_name", sa.String(255), nullable=True),
        sa.Column("restriction_type", sa.String(32), nullable=False),
        sa.Column("max_weight", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_height", sa.Numeric(10, 3), nullable=True),
        sa.Column("max_width", sa.Numeric(10, 3), nullable=True),
        sa.Column("max_length", sa.Numeric(10, 3), nullable=True),
        sa.Column("start_date", TS, nullable=True),
        sa.Column("end_date", TS, nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_route_restrictions"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_route_restrictions_tenant_id_tenants", ondelete="RESTRICT"),
        sa.CheckConstraint(
            "restriction_type IN ('weight_limit', 'height_limit', 'width_limit', "
            "'length_limit', 'time_window', 'hazardous_material', 'road_closure')",
            name="ck_route_restrictions_restriction_type",
        ),
    )
    op.create_index("ix_route_restrictions_tenant_id", "route_restrictions", ["tenant_id"])
    op.create_index("ix_route_restrictions_region", "route_restrictions", ["region"])
    op.create_index("ix_route_restrictions_restriction_type", "route_restrictions", ["restriction_type"])
    op.create_index("ix_route_restrictions_active", "route_restrictions", ["active"])

    # ----- permits -----
    op.create_table(
        "permits",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("permit_number", sa.String(64), nullable=False),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("equipment_id", UUID, nullable=True),
        sa.Column("vehicle_id", UUID, nullable=True),
        sa.Column("route_id", UUID, nullable=True),
        sa.Column("permit_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("issuing_authority", sa.String(255), nullable=True),
        sa.Column("region", sa.String(128), nullable=True),
        sa.Column("valid_from", TS, nullable=True),
        sa.Column("valid_until", TS, nullable=True),
        sa.Column("approved_at", TS, nullable=True),
        sa.Column("rejected_at", TS, nullable=True),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("expired_at", TS, nullable=True),
        sa.Column("requires_escort", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_police_escort", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("max_allowed_weight", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_allowed_height", sa.Numeric(10, 3), nullable=True),
        sa.Column("max_allowed_width", sa.Numeric(10, 3), nullable=True),
        sa.Column("max_allowed_length", sa.Numeric(10, 3), nullable=True),
        sa.Column("conditions", JSONB, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.String(512), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_permits"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_permits_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_permits_shipment_id_shipments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], name="fk_permits_equipment_id_equipment", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name="fk_permits_vehicle_id_vehicles", ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "permit_number", name="uq_permits_tenant_id_permit_number"),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'under_review', 'approved', 'rejected', "
            "'active', 'expired', 'cancelled')",
            name="ck_permits_status",
        ),
        sa.CheckConstraint(
            "permit_type IN ('oversize', 'overweight', 'government', 'municipal', "
            "'special_movement', 'site_entry')",
            name="ck_permits_permit_type",
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from",
            name="ck_permits_valid_window",
        ),
    )
    op.create_index("ix_permits_tenant_id", "permits", ["tenant_id"])
    op.create_index("ix_permits_status", "permits", ["status"])
    op.create_index("ix_permits_shipment_id", "permits", ["shipment_id"])
    op.create_index("ix_permits_equipment_id", "permits", ["equipment_id"])

    # ----- escorts -----
    op.create_table(
        "escorts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("permit_id", UUID, nullable=True),
        sa.Column("escort_type", sa.String(32), nullable=False),
        sa.Column("provider_name", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(64), nullable=True),
        sa.Column("start_location", sa.String(512), nullable=True),
        sa.Column("end_location", sa.String(512), nullable=True),
        sa.Column("scheduled_start", TS, nullable=True),
        sa.Column("scheduled_end", TS, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_escorts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_escorts_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_escorts_shipment_id_shipments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["permit_id"], ["permits.id"], name="fk_escorts_permit_id_permits", ondelete="SET NULL"),
        sa.CheckConstraint(
            "escort_type IN ('private_escort', 'police_escort', 'pilot_vehicle', 'technical_support')",
            name="ck_escorts_escort_type",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'scheduled', 'cancelled', 'completed')", name="ck_escorts_status"
        ),
    )
    op.create_index("ix_escorts_tenant_id", "escorts", ["tenant_id"])
    op.create_index("ix_escorts_shipment_id", "escorts", ["shipment_id"])
    op.create_index("ix_escorts_permit_id", "escorts", ["permit_id"])
    op.create_index("ix_escorts_status", "escorts", ["status"])

    # ----- axle_weight_profiles -----
    op.create_table(
        "axle_weight_profiles",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("equipment_id", UUID, nullable=True),
        sa.Column("vehicle_id", UUID, nullable=True),
        sa.Column("axle_count", sa.Integer(), nullable=True),
        sa.Column("total_weight", sa.Numeric(12, 2), nullable=True),
        sa.Column("axle_weights", JSONB, nullable=True),
        sa.Column("max_axle_weight", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_compliant", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_axle_weight_profiles"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_axle_weight_profiles_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], name="fk_axle_weight_profiles_equipment_id_equipment", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name="fk_axle_weight_profiles_vehicle_id_vehicles", ondelete="SET NULL"),
        sa.CheckConstraint("axle_count IS NULL OR axle_count >= 0", name="ck_axle_weight_profiles_axle_count_non_negative"),
        sa.CheckConstraint("total_weight IS NULL OR total_weight >= 0", name="ck_axle_weight_profiles_total_weight_non_negative"),
    )
    op.create_index("ix_axle_weight_profiles_tenant_id", "axle_weight_profiles", ["tenant_id"])
    op.create_index("ix_axle_weight_profiles_equipment_id", "axle_weight_profiles", ["equipment_id"])

    # ----- compliance_checks -----
    op.create_table(
        "compliance_checks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("equipment_id", UUID, nullable=True),
        sa.Column("vehicle_id", UUID, nullable=True),
        sa.Column("permit_id", UUID, nullable=True),
        sa.Column("check_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("result", sa.String(512), nullable=True),
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failure_reasons", JSONB, nullable=True),
        sa.Column("evaluated_at", TS, nullable=True),
        sa.Column("evaluated_by", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_compliance_checks"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_compliance_checks_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_compliance_checks_shipment_id_shipments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], name="fk_compliance_checks_equipment_id_equipment", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name="fk_compliance_checks_vehicle_id_vehicles", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["permit_id"], ["permits.id"], name="fk_compliance_checks_permit_id_permits", ondelete="SET NULL"),
        sa.CheckConstraint(
            "check_type IN ('permit_required', 'permit_validity', 'escort_required', "
            "'axle_weight', 'oversize', 'route_restriction', 'operator_certification', "
            "'insurance_required', 'hazardous_material')",
            name="ck_compliance_checks_check_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'passed', 'failed', 'warning', 'overridden')",
            name="ck_compliance_checks_status",
        ),
    )
    op.create_index("ix_compliance_checks_tenant_id", "compliance_checks", ["tenant_id"])
    op.create_index("ix_compliance_checks_shipment_id", "compliance_checks", ["shipment_id"])
    op.create_index("ix_compliance_checks_check_type", "compliance_checks", ["check_type"])
    op.create_index("ix_compliance_checks_status", "compliance_checks", ["status"])

    # ----- operator_certifications -----
    op.create_table(
        "operator_certifications",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("equipment_category_id", UUID, nullable=True),
        sa.Column("certification_type", sa.String(128), nullable=False),
        sa.Column("certification_number", sa.String(128), nullable=True),
        sa.Column("issuing_authority", sa.String(255), nullable=True),
        sa.Column("valid_from", TS, nullable=True),
        sa.Column("valid_until", TS, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_operator_certifications"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_operator_certifications_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_operator_certifications_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["equipment_category_id"], ["equipment_categories.id"], name="fk_operator_certifications_equipment_category_id_equipment_categories", ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('active', 'expired', 'suspended', 'revoked')", name="ck_operator_certifications_status"
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_until >= valid_from",
            name="ck_operator_certifications_valid_window",
        ),
    )
    op.create_index("ix_operator_certifications_tenant_id", "operator_certifications", ["tenant_id"])
    op.create_index("ix_operator_certifications_user_id", "operator_certifications", ["user_id"])
    op.create_index("ix_operator_certifications_status", "operator_certifications", ["status"])

    if _is_postgres():
        for table in _TABLES:
            _enable_rls(table)


def downgrade() -> None:
    if _is_postgres():
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("operator_certifications")
    op.drop_table("compliance_checks")
    op.drop_table("axle_weight_profiles")
    op.drop_table("escorts")
    op.drop_table("permits")
    op.drop_table("route_restrictions")
