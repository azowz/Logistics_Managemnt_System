"""Integration delivery worker & hardening — Sprint 14 (context #21).

Additive only. Adds secret-encryption metadata columns to ``webhook_subscriptions``
(``encryption_provider`` / ``encryption_key_id`` — so a KMS migration / key rotation is
auditable) and a composite index on ``webhook_deliveries(status, next_attempt_at)`` to
make the delivery-retry sweep efficient. No column is dropped/retyped, no source-domain
table is touched, and no secret is stored in plaintext. RLS is unaffected (no table
created). Reversible downgrade.

Revision ID: 0017_integration_delivery_worker_hardening
Revises:     0016_external_integrations_webhooks_domain
Create Date: 2026-07-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_integration_delivery_worker_hardening"
down_revision: Union[str, None] = "0016_external_integrations_webhooks_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("webhook_subscriptions", sa.Column("encryption_provider", sa.String(32), nullable=True))
    op.add_column("webhook_subscriptions", sa.Column("encryption_key_id", sa.String(64), nullable=True))
    # Composite index backing the due-delivery sweep (status + next_attempt_at scan).
    op.create_index(
        "ix_webhook_deliveries_status_next_attempt_at",
        "webhook_deliveries", ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_status_next_attempt_at", table_name="webhook_deliveries")
    op.drop_column("webhook_subscriptions", "encryption_key_id")
    op.drop_column("webhook_subscriptions", "encryption_provider")
