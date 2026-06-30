"""Reporting & Analytics projections — Sprint 11 (context #20, ADR-006/007).

Additive: creates the read-side ``proj_*`` projection tables + ``projection_health``.
All tenant-scoped (RLS), optimized for dashboard reads, and rebuildable from
``event_store``. No source-domain table is modified. PostgreSQL-specific
operations (RLS) are guarded by ``_is_postgres()``.

Revision ID: 0014_reporting_analytics_projections_domain
Revises:     0013_notifications_communications_domain
Create Date: 2026-06-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014_reporting_analytics_projections_domain"
down_revision: Union[str, None] = "0013_notifications_communications_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"

_TABLES = (
    "proj_shipment_performance", "proj_financial_summary", "proj_ar_aging",
    "proj_claims_metrics", "proj_compliance_metrics", "proj_notification_deliverability",
    "proj_operations_dashboard", "projection_health",
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _ts_cols():
    return [
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
    ]


def _int(name):
    return sa.Column(name, sa.Integer(), nullable=False, server_default=sa.text("0"))


def _amt(name, prec=16):
    return sa.Column(name, sa.Numeric(prec, 2), nullable=False, server_default="0")


def _rate(name):
    return sa.Column(name, sa.Numeric(6, 4), nullable=False, server_default="0")


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


def _fk_tenant(table):
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                   name=f"fk_{table}_tenant_id_tenants", ondelete="RESTRICT")


def upgrade() -> None:
    # ----- projection_health -----
    op.create_table(
        "projection_health",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("projection_name", sa.String(64), nullable=False),
        sa.Column("last_event_id", UUID, nullable=True),
        sa.Column("last_event_type", sa.String(128), nullable=True),
        sa.Column("last_applied_at", TS, nullable=True),
        _int("events_applied"),
        sa.Column("last_rebuilt_at", TS, nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_projection_health"),
        _fk_tenant("projection_health"),
        sa.UniqueConstraint("tenant_id", "projection_name", name="uq_projection_health_tenant_id_projection_name"),
    )
    op.create_index("ix_projection_health_tenant_id", "projection_health", ["tenant_id"])

    # ----- proj_shipment_performance -----
    op.create_table(
        "proj_shipment_performance",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        _int("total_shipments"), _int("assigned_shipments"), _int("in_transit_shipments"),
        _int("delivered_shipments"), _int("delayed_shipments"), _int("failed_shipments"),
        _int("returned_shipments"), _int("cancelled_shipments"), _int("on_time_deliveries"),
        _int("late_deliveries"), _amt("average_delivery_duration_minutes", 12), _rate("delay_rate"),
        _rate("failure_rate"),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_proj_shipment_performance"),
        _fk_tenant("proj_shipment_performance"),
        sa.UniqueConstraint("tenant_id", "period_date", name="uq_proj_shipment_performance_tenant_id_period_date"),
    )
    op.create_index("ix_proj_shipment_performance_tenant_id", "proj_shipment_performance", ["tenant_id"])
    op.create_index("ix_proj_shipment_performance_period_date", "proj_shipment_performance", ["period_date"])

    # ----- proj_financial_summary -----
    op.create_table(
        "proj_financial_summary",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        _int("total_quotes"), _int("approved_quotes"), _int("issued_invoices"),
        _int("paid_invoices"), _int("overdue_invoices"),
        _amt("gross_revenue"), _amt("collected_revenue"), _amt("outstanding_amount"),
        _amt("claim_adjustments"), _amt("penalties_amount"), _amt("settlement_amount"),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_proj_financial_summary"),
        _fk_tenant("proj_financial_summary"),
        sa.UniqueConstraint("tenant_id", "period_date", "currency_code", name="uq_proj_financial_summary_tenant_period_currency"),
    )
    op.create_index("ix_proj_financial_summary_tenant_id", "proj_financial_summary", ["tenant_id"])
    op.create_index("ix_proj_financial_summary_period_date", "proj_financial_summary", ["period_date"])

    # ----- proj_ar_aging -----
    op.create_table(
        "proj_ar_aging",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        _amt("current_amount"), _amt("days_1_30"), _amt("days_31_60"),
        _amt("days_61_90"), _amt("days_over_90"), _amt("total_outstanding"),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_proj_ar_aging"),
        _fk_tenant("proj_ar_aging"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_proj_ar_aging_customer_id_customers", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "customer_id", "currency_code", name="uq_proj_ar_aging_tenant_customer_currency"),
    )
    op.create_index("ix_proj_ar_aging_tenant_id", "proj_ar_aging", ["tenant_id"])
    op.create_index("ix_proj_ar_aging_customer_id", "proj_ar_aging", ["customer_id"])

    # ----- proj_claims_metrics -----
    op.create_table(
        "proj_claims_metrics",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="SAR"),
        _int("total_claims"), _int("approved_claims"), _int("rejected_claims"),
        _int("settled_claims"), _int("open_claims"),
        _amt("total_claimed_amount"), _amt("total_approved_amount"), _amt("total_settled_amount"),
        _amt("average_claim_cycle_days", 10),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_proj_claims_metrics"),
        _fk_tenant("proj_claims_metrics"),
        sa.UniqueConstraint("tenant_id", "period_date", "currency_code", name="uq_proj_claims_metrics_tenant_period_currency"),
    )
    op.create_index("ix_proj_claims_metrics_tenant_id", "proj_claims_metrics", ["tenant_id"])
    op.create_index("ix_proj_claims_metrics_period_date", "proj_claims_metrics", ["period_date"])

    # ----- proj_compliance_metrics -----
    op.create_table(
        "proj_compliance_metrics",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        _int("permits_created"), _int("permits_approved"), _int("permits_rejected"),
        _int("permits_expired"), _int("dispatch_blocks"), _int("dispatch_clears"),
        _int("compliance_failures"), _int("override_count"),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_proj_compliance_metrics"),
        _fk_tenant("proj_compliance_metrics"),
        sa.UniqueConstraint("tenant_id", "period_date", name="uq_proj_compliance_metrics_tenant_id_period_date"),
    )
    op.create_index("ix_proj_compliance_metrics_tenant_id", "proj_compliance_metrics", ["tenant_id"])
    op.create_index("ix_proj_compliance_metrics_period_date", "proj_compliance_metrics", ["period_date"])

    # ----- proj_notification_deliverability -----
    op.create_table(
        "proj_notification_deliverability",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        _int("total_notifications"), _int("sent_notifications"), _int("failed_notifications"),
        _int("read_notifications"), _int("retry_count"), _int("in_app_sent"),
        _int("email_failed"), _int("sms_failed"), _int("push_failed"), _int("webhook_failed"),
        _rate("read_rate"), _rate("failure_rate"),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_proj_notification_deliverability"),
        _fk_tenant("proj_notification_deliverability"),
        sa.UniqueConstraint("tenant_id", "period_date", name="uq_proj_notification_deliverability_tenant_id_period_date"),
    )
    op.create_index("ix_proj_notification_deliverability_tenant_id", "proj_notification_deliverability", ["tenant_id"])
    op.create_index("ix_proj_notification_deliverability_period_date", "proj_notification_deliverability", ["period_date"])

    # ----- proj_operations_dashboard -----
    op.create_table(
        "proj_operations_dashboard",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        _int("active_shipments"), _int("delayed_shipments"), _int("pending_compliance_blocks"),
        _int("unread_urgent_notifications"), _int("open_claims"), _int("outstanding_invoices"),
        _amt("total_revenue_period"),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_proj_operations_dashboard"),
        _fk_tenant("proj_operations_dashboard"),
        sa.UniqueConstraint("tenant_id", name="uq_proj_operations_dashboard_tenant_id"),
        sa.CheckConstraint("active_shipments >= 0", name="ck_proj_operations_dashboard_active_shipments_non_negative"),
    )
    op.create_index("ix_proj_operations_dashboard_tenant_id", "proj_operations_dashboard", ["tenant_id"])

    if _is_postgres():
        for table in _TABLES:
            _enable_rls(table)


def downgrade() -> None:
    if _is_postgres():
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("proj_operations_dashboard")
    op.drop_table("proj_notification_deliverability")
    op.drop_table("proj_compliance_metrics")
    op.drop_table("proj_claims_metrics")
    op.drop_table("proj_ar_aging")
    op.drop_table("proj_financial_summary")
    op.drop_table("proj_shipment_performance")
    op.drop_table("projection_health")
