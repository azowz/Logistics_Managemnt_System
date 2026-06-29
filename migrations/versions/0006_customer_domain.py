"""Customer domain — Sprint 3.

Creates the ``customers`` table with:
  * Full business identity columns (code, names, legal/tax, contact, address).
  * Tenant-scoped uniqueness for ``code``, ``commercial_registration``, and
    ``vat_number``.
  * ``status`` / ``risk_level`` / ``credit_status`` / ``customer_type`` with
    CHECK constraints.
  * Soft-delete support (``deleted_at``, ``deleted_by``).
  * Optimistic concurrency (``version``).
  * Timestamp and audit columns.
  * Row-Level Security (PostgreSQL only, mirrors migration 0003 pattern).

Revision ID: 0006_customer_domain
Revises:     0005_event_backbone
Create Date: 2026-06-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_customer_domain"
down_revision: Union[str, None] = "0005_event_backbone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "customers",
        # --- identity ---
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),

        # --- classification ---
        sa.Column(
            "customer_type",
            sa.String(32),
            nullable=False,
            server_default="corporate",
        ),
        sa.Column("industry", sa.String(128), nullable=True),

        # --- names ---
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("commercial_name", sa.String(255), nullable=True),

        # --- legal / tax ---
        sa.Column("tax_number", sa.String(64), nullable=True),
        sa.Column("commercial_registration", sa.String(64), nullable=True),
        sa.Column("vat_number", sa.String(64), nullable=True),

        # --- contact ---
        sa.Column("contact_person", sa.String(255), nullable=True),
        sa.Column("primary_phone", sa.String(32), nullable=True),
        sa.Column("secondary_phone", sa.String(32), nullable=True),
        sa.Column("primary_email", sa.String(255), nullable=True),
        sa.Column("secondary_email", sa.String(255), nullable=True),

        # --- address ---
        sa.Column("country", sa.String(128), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("district", sa.String(128), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),

        # --- preferences ---
        sa.Column("preferred_language", sa.String(8), nullable=True),

        # --- operational state ---
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="active"
        ),
        sa.Column(
            "risk_level", sa.String(32), nullable=False, server_default="low"
        ),
        sa.Column(
            "credit_status", sa.String(32), nullable=False, server_default="good"
        ),

        # --- free-form ---
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", JSONB, nullable=True),

        # --- timestamps (TimestampMixin) ---
        sa.Column(
            "created_at",
            TS,
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            TS,
            nullable=False,
            server_default=sa.text("now()"),
        ),

        # --- audit (AuditMixin) ---
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),

        # --- soft-delete (SoftDeleteMixin + extension) ---
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("deleted_by", UUID, nullable=True),

        # --- optimistic lock (ADR-004) ---
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),

        # --- constraints ---
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_customers_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_customers_tenant_id_code"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "commercial_registration",
            name="uq_customers_tenant_id_commercial_registration",
        ),
        sa.UniqueConstraint(
            "tenant_id", "vat_number", name="uq_customers_tenant_id_vat_number"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'inactive')",
            name="ck_customers_status",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_customers_risk_level",
        ),
        sa.CheckConstraint(
            "credit_status IN ('good', 'watch', 'blocked')",
            name="ck_customers_credit_status",
        ),
        sa.CheckConstraint(
            "customer_type IN ('individual', 'corporate', 'government', 'sme')",
            name="ck_customers_customer_type",
        ),
    )

    # --- indexes ---
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
    op.create_index("ix_customers_status", "customers", ["status"])
    op.create_index("ix_customers_primary_email", "customers", ["primary_email"])
    op.create_index("ix_customers_country", "customers", ["country"])
    op.create_index("ix_customers_city", "customers", ["city"])

    # --- Row-Level Security (PostgreSQL only, mirrors migration 0003) ---
    if _is_postgres():
        op.execute("ALTER TABLE customers ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE customers FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON customers
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
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON customers")
        op.execute("ALTER TABLE customers NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE customers DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_customers_city", table_name="customers")
    op.drop_index("ix_customers_country", table_name="customers")
    op.drop_index("ix_customers_primary_email", table_name="customers")
    op.drop_index("ix_customers_status", table_name="customers")
    op.drop_index("ix_customers_tenant_id", table_name="customers")
    op.drop_table("customers")
