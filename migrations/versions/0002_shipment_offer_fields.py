"""Add commercial offer fields to shipments (driver offer feed).

Adds nullable cargo_type, price_sar, required_vehicle_type to shipments so the
driver-facing offer endpoints (GET /v1/shipments/nearby) can present fare and
cargo information. All nullable — existing rows are unaffected.

Revision ID: 0002_shipment_offer_fields
Revises: 0001_baseline
Create Date: 2026-06-20
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_shipment_offer_fields"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shipments", sa.Column("cargo_type", sa.String(128), nullable=True))
    op.add_column("shipments", sa.Column("price_sar", sa.Numeric(12, 2), nullable=True))
    op.add_column(
        "shipments",
        sa.Column("required_vehicle_type", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shipments", "required_vehicle_type")
    op.drop_column("shipments", "price_sar")
    op.drop_column("shipments", "cargo_type")
