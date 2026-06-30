"""Notifications & Communications domain — Sprint 10 (context #19).

Additive: creates ``notification_templates``, ``notifications``,
``notification_delivery_attempts`` — tenant-scoped, RLS, soft-delete, audit,
optimistic lock, JSONB fields. A per-recipient idempotency unique constraint
``(tenant_id, idempotency_key)`` makes event-driven creation safe under replay.
No existing table is modified. PostgreSQL-specific operations (RLS, regex email
CHECK) are guarded by ``_is_postgres()``.

Revision ID: 0013_notifications_communications_domain
Revises:     0012_billing_settlements_domain
Create Date: 2026-06-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013_notifications_communications_domain"
down_revision: Union[str, None] = "0012_billing_settlements_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
TS = sa.DateTime(timezone=True)
NIL = "00000000-0000-0000-0000-000000000000"

# Drop order respects FKs (children before parents).
_TABLES = ("notification_delivery_attempts", "notifications", "notification_templates")
_RLS_TABLES = ("notification_templates", "notifications", "notification_delivery_attempts")

_EMAIL_CK = "recipient_email IS NULL OR recipient_email ~ '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'"


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
    # ----- notification_templates -----
    op.create_table(
        "notification_templates",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("template_code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("subject_template", sa.String(512), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("event_type", sa.String(128), nullable=True),
        sa.Column("variables_schema", JSONB, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_notification_templates"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_notification_templates_tenant_id_tenants", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "template_code", name="uq_notification_templates_tenant_id_template_code"),
        sa.CheckConstraint("channel IN ('in_app', 'email', 'sms', 'push', 'webhook')", name="ck_notification_templates_channel"),
    )
    op.create_index("ix_notification_templates_tenant_id", "notification_templates", ["tenant_id"])
    op.create_index("ix_notification_templates_channel", "notification_templates", ["channel"])
    op.create_index("ix_notification_templates_event_type", "notification_templates", ["event_type"])

    # ----- notifications -----
    op.create_table(
        "notifications",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("template_id", UUID, nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("event_id", UUID, nullable=True),
        sa.Column("event_type", sa.String(128), nullable=True),
        sa.Column("aggregate_type", sa.String(64), nullable=True),
        sa.Column("aggregate_id", UUID, nullable=True),
        sa.Column("recipient_user_id", UUID, nullable=True),
        sa.Column("recipient_email", sa.String(320), nullable=True),
        sa.Column("recipient_phone", sa.String(32), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("scheduled_at", TS, nullable=True),
        sa.Column("queued_at", TS, nullable=True),
        sa.Column("sent_at", TS, nullable=True),
        sa.Column("failed_at", TS, nullable=True),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("read_at", TS, nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_notifications_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_id"], ["notification_templates.id"], name="fk_notifications_template_id_notification_templates", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], name="fk_notifications_recipient_user_id_users", ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_notifications_tenant_id_idempotency_key"),
        sa.CheckConstraint("status IN ('pending', 'queued', 'sent', 'failed', 'cancelled', 'read')", name="ck_notifications_status"),
        sa.CheckConstraint("channel IN ('in_app', 'email', 'sms', 'push', 'webhook')", name="ck_notifications_channel"),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="ck_notifications_priority"),
        sa.CheckConstraint("retry_count >= 0", name="ck_notifications_retry_count_non_negative"),
        sa.CheckConstraint(
            "recipient_user_id IS NOT NULL OR recipient_email IS NOT NULL OR recipient_phone IS NOT NULL",
            name="ck_notifications_recipient_target_present",
        ),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
    op.create_index("ix_notifications_status", "notifications", ["status"])
    op.create_index("ix_notifications_channel", "notifications", ["channel"])
    op.create_index("ix_notifications_event_id", "notifications", ["event_id"])
    op.create_index("ix_notifications_event_type", "notifications", ["event_type"])
    op.create_index("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"])

    # ----- notification_delivery_attempts -----
    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("notification_id", UUID, nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("requested_at", TS, nullable=True),
        sa.Column("completed_at", TS, nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("response_payload", JSONB, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_notification_delivery_attempts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_notification_delivery_attempts_tenant_id_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], name="fk_notification_delivery_attempts_notification_id_notifications", ondelete="CASCADE"),
        sa.CheckConstraint("channel IN ('in_app', 'email', 'sms', 'push', 'webhook')", name="ck_notification_delivery_attempts_channel"),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'skipped', 'retrying')", name="ck_notification_delivery_attempts_status"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_notification_delivery_attempts_attempt_number_positive"),
    )
    op.create_index("ix_notification_delivery_attempts_tenant_id", "notification_delivery_attempts", ["tenant_id"])
    op.create_index("ix_notification_delivery_attempts_notification_id", "notification_delivery_attempts", ["notification_id"])

    # PostgreSQL-only: regex email CHECK + RLS.
    if _is_postgres():
        op.create_check_constraint("ck_notifications_recipient_email_format", "notifications", _EMAIL_CK)
        for table in _RLS_TABLES:
            _enable_rls(table)


def downgrade() -> None:
    if _is_postgres():
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("notification_delivery_attempts")
    op.drop_table("notifications")
    op.drop_table("notification_templates")
