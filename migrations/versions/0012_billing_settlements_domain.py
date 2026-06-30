"""Billing & Settlements domain — Sprint 9 (context #18, docs/09, docs/10).

Additive: creates ``quotes``, ``invoices``, ``invoice_lines``, ``payments``,
``settlements``, ``payouts``, ``penalties`` — tenant-scoped, RLS, soft-delete,
audit, optimistic lock, JSONB fields. No existing table is modified.
PostgreSQL-specific operations (RLS) guarded by ``_is_postgres()``.

Revision ID: 0012_billing_settlements_domain
Revises:     0011_insurance_claims_domain
Create Date: 2026-06-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_billing_settlements_domain"
down_revision: Union[str, None] = "0011_insurance_claims_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"

# Drop order respects FKs (children before parents).
_TABLES = ("penalties", "payouts", "settlements", "payments", "invoice_lines", "invoices", "quotes")
_RLS_TABLES = ("quotes", "invoices", "invoice_lines", "payments", "settlements", "payouts", "penalties")


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
    # ----- quotes -----
    op.create_table(
        "quotes",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("quote_number", sa.String(64), nullable=False),
        sa.Column("customer_id", UUID, nullable=True),
        sa.Column("order_id", UUID, nullable=True),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("subtotal_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("valid_until", TS, nullable=True),
        sa.Column("issued_at", TS, nullable=True),
        sa.Column("approved_at", TS, nullable=True),
        sa.Column("rejected_at", TS, nullable=True),
        sa.Column("expired_at", TS, nullable=True),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("terms", JSONB, nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_quotes"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_quotes_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_quotes_customer_id_customers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_quotes_order_id_orders", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_quotes_shipment_id_shipments", ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "quote_number", name="uq_quotes_tenant_id_quote_number"),
        sa.CheckConstraint("status IN ('draft', 'issued', 'approved', 'rejected', 'expired', 'cancelled')", name="ck_quotes_status"),
        sa.CheckConstraint("subtotal_amount >= 0", name="ck_quotes_subtotal_non_negative"),
        sa.CheckConstraint("tax_amount >= 0", name="ck_quotes_tax_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_quotes_discount_non_negative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_quotes_total_non_negative"),
    )
    op.create_index("ix_quotes_tenant_id", "quotes", ["tenant_id"])
    op.create_index("ix_quotes_status", "quotes", ["status"])
    op.create_index("ix_quotes_customer_id", "quotes", ["customer_id"])
    op.create_index("ix_quotes_order_id", "quotes", ["order_id"])
    op.create_index("ix_quotes_shipment_id", "quotes", ["shipment_id"])

    # ----- invoices -----
    op.create_table(
        "invoices",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("invoice_number", sa.String(64), nullable=False),
        sa.Column("customer_id", UUID, nullable=True),
        sa.Column("order_id", UUID, nullable=True),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("quote_id", UUID, nullable=True),
        sa.Column("claim_id", UUID, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("subtotal_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("penalty_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("claim_adjustment_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("is_credit_note", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("due_date", TS, nullable=True),
        sa.Column("issued_at", TS, nullable=True),
        sa.Column("paid_at", TS, nullable=True),
        sa.Column("voided_at", TS, nullable=True),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_invoices_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_invoices_customer_id_customers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_invoices_order_id_orders", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_invoices_shipment_id_shipments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], name="fk_invoices_quote_id_quotes", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], name="fk_invoices_claim_id_claims", ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "invoice_number", name="uq_invoices_tenant_id_invoice_number"),
        sa.CheckConstraint("status IN ('draft', 'issued', 'partially_paid', 'paid', 'overdue', 'voided', 'cancelled')", name="ck_invoices_status"),
        sa.CheckConstraint("subtotal_amount >= 0", name="ck_invoices_subtotal_non_negative"),
        sa.CheckConstraint("tax_amount >= 0", name="ck_invoices_tax_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_invoices_discount_non_negative"),
        sa.CheckConstraint("penalty_amount >= 0", name="ck_invoices_penalty_non_negative"),
        sa.CheckConstraint("claim_adjustment_amount >= 0", name="ck_invoices_claim_adjustment_non_negative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_invoices_total_non_negative"),
    )
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])
    op.create_index("ix_invoices_customer_id", "invoices", ["customer_id"])
    op.create_index("ix_invoices_order_id", "invoices", ["order_id"])
    op.create_index("ix_invoices_shipment_id", "invoices", ["shipment_id"])
    op.create_index("ix_invoices_claim_id", "invoices", ["claim_id"])

    # ----- invoice_lines -----
    op.create_table(
        "invoice_lines",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("invoice_id", UUID, nullable=False),
        sa.Column("line_type", sa.String(32), nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("reference_type", sa.String(16), nullable=True),
        sa.Column("reference_id", UUID, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_lines"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_invoice_lines_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_invoice_lines_invoice_id_invoices", ondelete="CASCADE"),
        sa.CheckConstraint("line_type IN ('transport_fee', 'equipment_fee', 'permit_fee', 'escort_fee', 'storage_fee', 'penalty', 'claim_adjustment', 'cancellation_fee', 'discount', 'tax')", name="ck_invoice_lines_line_type"),
        sa.CheckConstraint("quantity > 0", name="ck_invoice_lines_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_invoice_lines_unit_price_non_negative"),
        sa.CheckConstraint("tax_rate >= 0", name="ck_invoice_lines_tax_rate_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_invoice_lines_discount_non_negative"),
    )
    op.create_index("ix_invoice_lines_tenant_id", "invoice_lines", ["tenant_id"])
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])

    # ----- payments -----
    op.create_table(
        "payments",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("invoice_id", UUID, nullable=False),
        sa.Column("payment_reference", sa.String(128), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="confirmed"),
        sa.Column("paid_at", TS, nullable=True),
        sa.Column("received_by", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_payments_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_payments_invoice_id_invoices", ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'failed', 'reversed')", name="ck_payments_status"),
        sa.CheckConstraint("method IN ('bank_transfer', 'cash', 'card', 'sadad', 'internal_adjustment')", name="ck_payments_method"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"])
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])
    op.create_index("ix_payments_status", "payments", ["status"])

    # ----- settlements -----
    op.create_table(
        "settlements",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("settlement_number", sa.String(64), nullable=False),
        sa.Column("claim_id", UUID, nullable=True),
        sa.Column("invoice_id", UUID, nullable=True),
        sa.Column("customer_id", UUID, nullable=True),
        sa.Column("equipment_id", UUID, nullable=True),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("settlement_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("approved_at", TS, nullable=True),
        sa.Column("settled_at", TS, nullable=True),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_settlements"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_settlements_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], name="fk_settlements_claim_id_claims", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_settlements_invoice_id_invoices", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_settlements_customer_id_customers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], name="fk_settlements_equipment_id_equipment", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_settlements_shipment_id_shipments", ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "settlement_number", name="uq_settlements_tenant_id_settlement_number"),
        sa.CheckConstraint("status IN ('draft', 'pending_approval', 'approved', 'settled', 'cancelled')", name="ck_settlements_status"),
        sa.CheckConstraint("settlement_type IN ('claim_payout', 'claim_offset', 'customer_refund', 'carrier_payout', 'penalty_deduction')", name="ck_settlements_settlement_type"),
        sa.CheckConstraint("amount >= 0", name="ck_settlements_amount_non_negative"),
    )
    op.create_index("ix_settlements_tenant_id", "settlements", ["tenant_id"])
    op.create_index("ix_settlements_status", "settlements", ["status"])
    op.create_index("ix_settlements_claim_id", "settlements", ["claim_id"])
    op.create_index("ix_settlements_invoice_id", "settlements", ["invoice_id"])

    # ----- payouts -----
    op.create_table(
        "payouts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("settlement_id", UUID, nullable=False),
        sa.Column("payout_reference", sa.String(128), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("paid_at", TS, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_payouts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_payouts_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["settlement_id"], ["settlements.id"], name="fk_payouts_settlement_id_settlements", ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('pending', 'paid', 'failed')", name="ck_payouts_status"),
        sa.CheckConstraint("method IN ('bank_transfer', 'cash', 'card', 'sadad', 'internal_adjustment')", name="ck_payouts_method"),
        sa.CheckConstraint("amount >= 0", name="ck_payouts_amount_non_negative"),
    )
    op.create_index("ix_payouts_tenant_id", "payouts", ["tenant_id"])
    op.create_index("ix_payouts_settlement_id", "payouts", ["settlement_id"])

    # ----- penalties -----
    op.create_table(
        "penalties",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("order_id", UUID, nullable=True),
        sa.Column("shipment_id", UUID, nullable=True),
        sa.Column("invoice_id", UUID, nullable=True),
        sa.Column("penalty_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("applied_at", TS, nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_penalties"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_penalties_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_penalties_order_id_orders", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"], name="fk_penalties_shipment_id_shipments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_penalties_invoice_id_invoices", ondelete="SET NULL"),
        sa.CheckConstraint("penalty_type IN ('late_delivery', 'cancellation_fee', 'compliance_violation', 'damage', 'other')", name="ck_penalties_penalty_type"),
        sa.CheckConstraint("amount >= 0", name="ck_penalties_amount_non_negative"),
    )
    op.create_index("ix_penalties_tenant_id", "penalties", ["tenant_id"])
    op.create_index("ix_penalties_order_id", "penalties", ["order_id"])
    op.create_index("ix_penalties_shipment_id", "penalties", ["shipment_id"])

    if _is_postgres():
        for table in _RLS_TABLES:
            _enable_rls(table)


def downgrade() -> None:
    if _is_postgres():
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("penalties")
    op.drop_table("payouts")
    op.drop_table("settlements")
    op.drop_table("payments")
    op.drop_table("invoice_lines")
    op.drop_table("invoices")
    op.drop_table("quotes")
