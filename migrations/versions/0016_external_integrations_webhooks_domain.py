"""External Integrations & Webhooks domain — Sprint 13 (context #21).

Additive: creates ``integration_partners``, ``partner_api_keys``,
``webhook_subscriptions``, ``webhook_deliveries``, ``webhook_delivery_attempts``,
``inbound_integration_events`` — tenant-scoped, RLS, with soft-delete/audit/optimistic
lock where the model uses them. Idempotency unique constraints back the webhook
consumer (``(tenant_id, subscription_id, source_event_id)``) and inbound de-dup
(``(tenant_id, api_key_id, idempotency_key)``). No existing table is modified.
PostgreSQL-specific operations (RLS) are guarded by ``_is_postgres()``.

Revision ID: 0016_external_integrations_webhooks_domain
Revises:     0015_event_enrichment_analytics_hardening
Create Date: 2026-07-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0016_external_integrations_webhooks_domain"
down_revision: Union[str, None] = "0015_event_enrichment_analytics_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"

_TABLES = (
    "integration_partners", "partner_api_keys", "webhook_subscriptions",
    "webhook_deliveries", "webhook_delivery_attempts", "inbound_integration_events",
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _timestamps():
    return [
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
    ]


def _audit_soft_delete():
    return [
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
    # --- integration_partners -------------------------------------------
    op.create_table(
        "integration_partners",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("partner_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("contact_email", sa.String(320), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("partner_metadata", JSONB, nullable=True),
        *_timestamps(),
        *_audit_soft_delete(),
        sa.PrimaryKeyConstraint("id", name="pk_integration_partners"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_integration_partners_tenant_id_tenants", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_integration_partners_tenant_id_name"),
        sa.CheckConstraint(
            "partner_type IN ('customer', 'carrier', 'vendor', 'government', 'internal', 'other')",
            name="ck_integration_partners_partner_type"),
        sa.CheckConstraint("status IN ('active', 'inactive', 'suspended')",
                           name="ck_integration_partners_status"),
    )
    op.create_index("ix_integration_partners_tenant_id", "integration_partners", ["tenant_id"])
    op.create_index("ix_integration_partners_partner_type", "integration_partners", ["partner_type"])
    op.create_index("ix_integration_partners_status", "integration_partners", ["status"])

    # --- partner_api_keys -----------------------------------------------
    op.create_table(
        "partner_api_keys",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("partner_id", UUID, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(32), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("scopes", JSONB, nullable=True),
        sa.Column("allowed_ips", JSONB, nullable=True),
        sa.Column("expires_at", TS, nullable=True),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("revoked_by", UUID, nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_partner_api_keys"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_partner_api_keys_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["partner_id"], ["integration_partners.id"],
                                name="fk_partner_api_keys_partner_id_integration_partners", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "key_prefix", name="uq_partner_api_keys_tenant_id_key_prefix"),
        sa.CheckConstraint("status IN ('active', 'revoked', 'expired')", name="ck_partner_api_keys_status"),
    )
    op.create_index("ix_partner_api_keys_tenant_id", "partner_api_keys", ["tenant_id"])
    op.create_index("ix_partner_api_keys_partner_id", "partner_api_keys", ["partner_id"])
    op.create_index("ix_partner_api_keys_key_prefix", "partner_api_keys", ["key_prefix"])
    op.create_index("ix_partner_api_keys_status", "partner_api_keys", ["status"])

    # --- webhook_subscriptions ------------------------------------------
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("partner_id", UUID, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("target_url", sa.String(2048), nullable=False),
        sa.Column("event_types", JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("signing_algorithm", sa.String(16), nullable=False, server_default="hmac_sha256"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("subscription_metadata", JSONB, nullable=True),
        *_timestamps(),
        *_audit_soft_delete(),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_subscriptions"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_webhook_subscriptions_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["partner_id"], ["integration_partners.id"],
                                name="fk_webhook_subscriptions_partner_id_integration_partners", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "partner_id", "name",
                            name="uq_webhook_subscriptions_tenant_partner_name"),
        sa.CheckConstraint("status IN ('active', 'inactive', 'suspended')",
                           name="ck_webhook_subscriptions_status"),
        sa.CheckConstraint("max_retries >= 0", name="ck_webhook_subscriptions_max_retries_non_negative"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_webhook_subscriptions_timeout_positive"),
    )
    op.create_index("ix_webhook_subscriptions_tenant_id", "webhook_subscriptions", ["tenant_id"])
    op.create_index("ix_webhook_subscriptions_partner_id", "webhook_subscriptions", ["partner_id"])
    op.create_index("ix_webhook_subscriptions_status", "webhook_subscriptions", ["status"])

    # --- webhook_deliveries ---------------------------------------------
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("subscription_id", UUID, nullable=False),
        sa.Column("partner_id", UUID, nullable=False),
        sa.Column("source_event_id", UUID, nullable=False),
        sa.Column("source_event_type", sa.String(128), nullable=False),
        sa.Column("external_event_type", sa.String(128), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=True),
        sa.Column("aggregate_id", UUID, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(128), nullable=False),
        sa.Column("next_attempt_at", TS, nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", TS, nullable=True),
        sa.Column("delivered_at", TS, nullable=True),
        sa.Column("failed_at", TS, nullable=True),
        sa.Column("last_error", sa.String(1024), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_deliveries"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_webhook_deliveries_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["webhook_subscriptions.id"],
                                name="fk_webhook_deliveries_subscription_id_webhook_subscriptions", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["partner_id"], ["integration_partners.id"],
                                name="fk_webhook_deliveries_partner_id_integration_partners", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "subscription_id", "source_event_id",
                            name="uq_webhook_deliveries_tenant_subscription_source_event"),
        sa.CheckConstraint(
            "status IN ('pending', 'delivering', 'delivered', 'failed', 'cancelled', 'skipped')",
            name="ck_webhook_deliveries_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_webhook_deliveries_attempt_count_non_negative"),
    )
    op.create_index("ix_webhook_deliveries_tenant_id", "webhook_deliveries", ["tenant_id"])
    op.create_index("ix_webhook_deliveries_subscription_id", "webhook_deliveries", ["subscription_id"])
    op.create_index("ix_webhook_deliveries_partner_id", "webhook_deliveries", ["partner_id"])
    op.create_index("ix_webhook_deliveries_source_event_id", "webhook_deliveries", ["source_event_id"])
    op.create_index("ix_webhook_deliveries_external_event_type", "webhook_deliveries", ["external_event_type"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])
    op.create_index("ix_webhook_deliveries_next_attempt_at", "webhook_deliveries", ["next_attempt_at"])

    # --- webhook_delivery_attempts --------------------------------------
    op.create_table(
        "webhook_delivery_attempts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("delivery_id", UUID, nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_at", TS, nullable=True),
        sa.Column("completed_at", TS, nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_delivery_attempts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_webhook_delivery_attempts_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["delivery_id"], ["webhook_deliveries.id"],
                                name="fk_webhook_delivery_attempts_delivery_id_webhook_deliveries", ondelete="CASCADE"),
        sa.UniqueConstraint("delivery_id", "attempt_number",
                            name="uq_webhook_delivery_attempts_delivery_attempt"),
        sa.CheckConstraint("status IN ('succeeded', 'failed', 'skipped')",
                           name="ck_webhook_delivery_attempts_status"),
    )
    op.create_index("ix_webhook_delivery_attempts_tenant_id", "webhook_delivery_attempts", ["tenant_id"])
    op.create_index("ix_webhook_delivery_attempts_delivery_id", "webhook_delivery_attempts", ["delivery_id"])

    # --- inbound_integration_events -------------------------------------
    op.create_table(
        "inbound_integration_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("partner_id", UUID, nullable=False),
        sa.Column("api_key_id", UUID, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(16), nullable=False, server_default="received"),
        sa.Column("received_at", TS, nullable=True),
        sa.Column("processed_at", TS, nullable=True),
        sa.Column("rejected_at", TS, nullable=True),
        sa.Column("rejection_reason", sa.String(512), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_inbound_integration_events"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name="fk_inbound_integration_events_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["partner_id"], ["integration_partners.id"],
                                name="fk_inbound_integration_events_partner_id_integration_partners", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["api_key_id"], ["partner_api_keys.id"],
                                name="fk_inbound_integration_events_api_key_id_partner_api_keys", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "api_key_id", "idempotency_key",
                            name="uq_inbound_integration_events_tenant_apikey_idempotency"),
        sa.CheckConstraint(
            "status IN ('received', 'accepted', 'rejected', 'processed', 'failed')",
            name="ck_inbound_integration_events_status"),
    )
    op.create_index("ix_inbound_integration_events_tenant_id", "inbound_integration_events", ["tenant_id"])
    op.create_index("ix_inbound_integration_events_partner_id", "inbound_integration_events", ["partner_id"])
    op.create_index("ix_inbound_integration_events_api_key_id", "inbound_integration_events", ["api_key_id"])
    op.create_index("ix_inbound_integration_events_event_type", "inbound_integration_events", ["event_type"])
    op.create_index("ix_inbound_integration_events_status", "inbound_integration_events", ["status"])

    if _is_postgres():
        for table in _TABLES:
            _enable_rls(table)


def downgrade() -> None:
    if _is_postgres():
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("inbound_integration_events")
    op.drop_table("webhook_delivery_attempts")
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_subscriptions")
    op.drop_table("partner_api_keys")
    op.drop_table("integration_partners")
