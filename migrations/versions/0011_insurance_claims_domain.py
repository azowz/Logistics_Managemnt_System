"""Insurance & Claims domain — Sprint 8 (context #17, ADR-008 docs/08 Part 5).

Additive: creates ``insurance_policies``, ``coverage_rules``, ``claims``,
``damage_reports``, ``liability_records`` — tenant-scoped, RLS, soft-delete,
audit, optimistic lock, JSONB fields. No existing table is modified.
PostgreSQL-specific operations (RLS) guarded by ``_is_postgres()``.

Revision ID: 0011_insurance_claims_domain
Revises:     0010_compliance_permits_domain
Create Date: 2026-06-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011_insurance_claims_domain"
down_revision: Union[str, None] = "0010_compliance_permits_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"

_TABLES = ("liability_records", "damage_reports", "claims", "coverage_rules", "insurance_policies")


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
    # ----- insurance_policies -----
    op.create_table(
        "insurance_policies",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("policy_number", sa.String(64), nullable=False),
        sa.Column("provider_name", sa.String(255), nullable=True),
        sa.Column("policy_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("coverage_start_date", TS, nullable=True),
        sa.Column("coverage_end_date", TS, nullable=True),
        sa.Column("coverage_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("deductible_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("covers_equipment", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("covers_shipment", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("covers_third_party", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("covers_hazardous_cargo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("terms", JSONB, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_insurance_policies"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_insurance_policies_tenant_id_tenants", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "policy_number", name="uq_insurance_policies_tenant_id_policy_number"),
        sa.CheckConstraint("status IN ('draft', 'active', 'suspended', 'expired', 'cancelled')", name="ck_insurance_policies_status"),
        sa.CheckConstraint("policy_type IN ('cargo', 'equipment_in_transit', 'third_party_liability', 'project_car_ear', 'marine_inland')", name="ck_insurance_policies_policy_type"),
        sa.CheckConstraint("coverage_amount IS NULL OR coverage_amount >= 0", name="ck_insurance_policies_coverage_amount_non_negative"),
        sa.CheckConstraint("deductible_amount IS NULL OR deductible_amount >= 0", name="ck_insurance_policies_deductible_non_negative"),
        sa.CheckConstraint("coverage_start_date IS NULL OR coverage_end_date IS NULL OR coverage_end_date >= coverage_start_date", name="ck_insurance_policies_coverage_window"),
    )
    op.create_index("ix_insurance_policies_tenant_id", "insurance_policies", ["tenant_id"])
    op.create_index("ix_insurance_policies_status", "insurance_policies", ["status"])

    # ----- coverage_rules -----
    op.create_table(
        "coverage_rules",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("policy_id", UUID, nullable=False),
        sa.Column("coverage_type", sa.String(32), nullable=False),
        sa.Column("cargo_type", sa.String(128), nullable=True),
        sa.Column("equipment_category_id", UUID, nullable=True),
        sa.Column("max_coverage_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("deductible_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("requires_compliance_clearance", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("exclusions", JSONB, nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_coverage_rules"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_coverage_rules_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["policy_id"], ["insurance_policies.id"], name="fk_coverage_rules_policy_id_insurance_policies", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["equipment_category_id"], ["equipment_categories.id"], name="fk_coverage_rules_equipment_category_id_equipment_categories", ondelete="SET NULL"),
        sa.CheckConstraint("coverage_type IN ('shipment_loss', 'shipment_damage', 'equipment_damage', 'third_party_liability', 'delay_penalty', 'hazardous_cargo')", name="ck_coverage_rules_coverage_type"),
        sa.CheckConstraint("max_coverage_amount IS NULL OR max_coverage_amount >= 0", name="ck_coverage_rules_max_coverage_non_negative"),
    )
    op.create_index("ix_coverage_rules_tenant_id", "coverage_rules", ["tenant_id"])
    op.create_index("ix_coverage_rules_policy_id", "coverage_rules", ["policy_id"])

    # ----- claims -----
    op.create_table(
        "claims",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("claim_number", sa.String(64), nullable=False),
        sa.Column("policy_id", UUID, nullable=True),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("order_id", UUID, nullable=True),
        sa.Column("customer_id", UUID, nullable=True),
        sa.Column("equipment_id", UUID, nullable=True),
        sa.Column("compliance_check_id", UUID, nullable=True),
        sa.Column("permit_id", UUID, nullable=True),
        sa.Column("claim_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("incident_date", TS, nullable=True),
        sa.Column("reported_at", TS, nullable=True),
        sa.Column("reviewed_at", TS, nullable=True),
        sa.Column("approved_at", TS, nullable=True),
        sa.Column("rejected_at", TS, nullable=True),
        sa.Column("settled_at", TS, nullable=True),
        sa.Column("closed_at", TS, nullable=True),
        sa.Column("reopened_at", TS, nullable=True),
        sa.Column("claimed_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("approved_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.String(512), nullable=True),
        sa.Column("settlement_notes", sa.Text(), nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_claims"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_claims_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["policy_id"], ["insurance_policies.id"], name="fk_claims_policy_id_insurance_policies", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_claims_shipment_id_shipments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_claims_order_id_orders", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_claims_customer_id_customers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], name="fk_claims_equipment_id_equipment", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["compliance_check_id"], ["compliance_checks.id"], name="fk_claims_compliance_check_id_compliance_checks", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["permit_id"], ["permits.id"], name="fk_claims_permit_id_permits", ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "claim_number", name="uq_claims_tenant_id_claim_number"),
        sa.CheckConstraint("status IN ('created', 'under_review', 'approved', 'rejected', 'settled', 'closed')", name="ck_claims_status"),
        sa.CheckConstraint("claim_type IN ('shipment_loss', 'shipment_damage', 'equipment_damage', 'delay_claim', 'third_party_liability', 'compliance_violation')", name="ck_claims_claim_type"),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_claims_severity"),
        sa.CheckConstraint("claimed_amount IS NULL OR claimed_amount >= 0", name="ck_claims_claimed_amount_non_negative"),
        sa.CheckConstraint("approved_amount IS NULL OR approved_amount >= 0", name="ck_claims_approved_amount_non_negative"),
    )
    op.create_index("ix_claims_tenant_id", "claims", ["tenant_id"])
    op.create_index("ix_claims_status", "claims", ["status"])
    op.create_index("ix_claims_policy_id", "claims", ["policy_id"])
    op.create_index("ix_claims_shipment_id", "claims", ["shipment_id"])
    op.create_index("ix_claims_equipment_id", "claims", ["equipment_id"])

    # ----- damage_reports -----
    op.create_table(
        "damage_reports",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("claim_id", UUID, nullable=False),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("equipment_id", UUID, nullable=True),
        sa.Column("damage_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("photos", JSONB, nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("reported_by", UUID, nullable=True),
        sa.Column("reported_at", TS, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_damage_reports"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_damage_reports_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], name="fk_damage_reports_claim_id_claims", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_damage_reports_shipment_id_shipments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], name="fk_damage_reports_equipment_id_equipment", ondelete="SET NULL"),
        sa.CheckConstraint("damage_type IN ('cargo_damage', 'equipment_damage', 'vehicle_damage', 'property_damage', 'missing_items', 'delay_damage')", name="ck_damage_reports_damage_type"),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_damage_reports_severity"),
        sa.CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="ck_damage_reports_estimated_cost_non_negative"),
    )
    op.create_index("ix_damage_reports_tenant_id", "damage_reports", ["tenant_id"])
    op.create_index("ix_damage_reports_claim_id", "damage_reports", ["claim_id"])

    # ----- liability_records -----
    op.create_table(
        "liability_records",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("claim_id", UUID, nullable=False),
        sa.Column("responsible_party_type", sa.String(32), nullable=False),
        sa.Column("responsible_party_id", UUID, nullable=True),
        sa.Column("liability_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("liability_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("determination_reason", sa.Text(), nullable=True),
        sa.Column("determined_by", UUID, nullable=True),
        sa.Column("determined_at", TS, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_liability_records"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_liability_records_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], name="fk_liability_records_claim_id_claims", ondelete="CASCADE"),
        sa.CheckConstraint("responsible_party_type IN ('customer', 'carrier', 'driver', 'company', 'third_party', 'unknown')", name="ck_liability_records_responsible_party_type"),
        sa.CheckConstraint("liability_percentage IS NULL OR (liability_percentage >= 0 AND liability_percentage <= 100)", name="ck_liability_records_liability_percentage_range"),
        sa.CheckConstraint("liability_amount IS NULL OR liability_amount >= 0", name="ck_liability_records_liability_amount_non_negative"),
    )
    op.create_index("ix_liability_records_tenant_id", "liability_records", ["tenant_id"])
    op.create_index("ix_liability_records_claim_id", "liability_records", ["claim_id"])

    if _is_postgres():
        for table in ("insurance_policies", "coverage_rules", "claims", "damage_reports", "liability_records"):
            _enable_rls(table)


def downgrade() -> None:
    if _is_postgres():
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("liability_records")
    op.drop_table("damage_reports")
    op.drop_table("claims")
    op.drop_table("coverage_rules")
    op.drop_table("insurance_policies")
