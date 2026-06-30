"""Event enrichment & analytics hardening — Sprint 12 (context #20).

Purely additive. Adds internal sample-count columns backing the incremental
delivery-duration / claim-cycle means, plus projection-health automation columns
(``status`` and diagnostics). No event rows are touched, no source-domain table is
modified, and no projection column is dropped or retyped — existing rows keep their
values and the new columns default to a neutral/zero state. All new numeric columns
are NOT NULL with a server_default so back-filling is implicit.

Revision ID: 0015_event_enrichment_analytics_hardening
Revises:     0014_reporting_analytics_projections_domain
Create Date: 2026-06-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_event_enrichment_analytics_hardening"
down_revision: Union[str, None] = "0014_reporting_analytics_projections_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # --- projection sample counters (internal; back the incremental means) ---
    op.add_column(
        "proj_shipment_performance",
        sa.Column("delivery_duration_sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "proj_claims_metrics",
        sa.Column("claim_cycle_sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # --- projection_health automation columns ---
    op.add_column(
        "projection_health",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="healthy"),
    )
    op.add_column("projection_health", sa.Column("last_success_at", TS, nullable=True))
    op.add_column("projection_health", sa.Column("last_failure_at", TS, nullable=True))
    op.add_column("projection_health", sa.Column("last_error", sa.String(length=512), nullable=True))
    op.add_column("projection_health", sa.Column("last_event_occurred_at", TS, nullable=True))
    op.add_column(
        "projection_health",
        sa.Column("rebuild_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("projection_health", "rebuild_count")
    op.drop_column("projection_health", "last_event_occurred_at")
    op.drop_column("projection_health", "last_error")
    op.drop_column("projection_health", "last_failure_at")
    op.drop_column("projection_health", "last_success_at")
    op.drop_column("projection_health", "status")
    op.drop_column("proj_claims_metrics", "claim_cycle_sample_count")
    op.drop_column("proj_shipment_performance", "delivery_duration_sample_count")
