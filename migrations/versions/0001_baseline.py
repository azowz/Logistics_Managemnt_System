"""Baseline schema — mirrors app/models/* as of Phase 2.

Hand-authored to exactly match the existing SQLAlchemy models (no autogenerate
was run against a live DB). Constraint names follow app/db/base.py
NAMING_CONVENTION. Enums use native_enum=False (stored as VARCHAR + CHECK),
matching the model definitions.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-20
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)

USER_ROLE = sa.Enum(
    "admin", "manager", "driver", "client",
    name="userrole", native_enum=False, length=32,
)
VEHICLE_STATUS = sa.Enum(
    "active", "maintenance", "decommissioned",
    name="vehiclestatus", native_enum=False, length=32,
)
SHIPMENT_STATUS = sa.Enum(
    "created", "ready", "assigned", "in_transit",
    "delivered", "cancelled", "returned", "failed",
    name="shipmentstatus", native_enum=False, length=32,
)
EVENT_TYPE = sa.Enum(
    "status_update", "location_update", "proof_of_delivery", "exception",
    name="trackingeventtype", native_enum=False, length=32,
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    # ----- users -----
    op.create_table(
        "users",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ----- warehouses -----
    op.create_table(
        "warehouses",
        sa.Column("id", UUID, nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address_line1", sa.String(255), nullable=False),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(128), nullable=False),
        sa.Column("state", sa.String(128), nullable=True),
        sa.Column("country", sa.String(128), nullable=False),
        sa.Column("postal_code", sa.String(32), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("capacity_weight_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("capacity_volume_m3", sa.Numeric(12, 3), nullable=False),
        sa.Column("max_daily_shipments", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_warehouses"),
        sa.UniqueConstraint("code", name="uq_warehouses_code"),
    )

    # ----- drivers -----
    op.create_table(
        "drivers",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("license_number", sa.String(64), nullable=False),
        sa.Column("license_class", sa.String(32), nullable=True),
        sa.Column("phone_number", sa.String(32), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("home_warehouse_id", UUID, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_drivers"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_drivers_user_id_users", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["home_warehouse_id"], ["warehouses.id"],
            name="fk_drivers_home_warehouse_id_warehouses", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("user_id", name="uq_drivers_user_id"),
        sa.UniqueConstraint("license_number", name="uq_drivers_license_number"),
    )

    # ----- vehicles -----
    op.create_table(
        "vehicles",
        sa.Column("id", UUID, nullable=False),
        sa.Column("plate_number", sa.String(32), nullable=False),
        sa.Column("vin", sa.String(64), nullable=True),
        sa.Column("status", VEHICLE_STATUS, nullable=False),
        sa.Column("capacity_weight_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("capacity_volume_m3", sa.Numeric(12, 3), nullable=False),
        sa.Column("home_warehouse_id", UUID, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_vehicles"),
        sa.ForeignKeyConstraint(
            ["home_warehouse_id"], ["warehouses.id"],
            name="fk_vehicles_home_warehouse_id_warehouses", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("plate_number", name="uq_vehicles_plate_number"),
        sa.UniqueConstraint("vin", name="uq_vehicles_vin"),
    )

    # ----- shipments -----
    op.create_table(
        "shipments",
        sa.Column("id", UUID, nullable=False),
        sa.Column("reference_code", sa.String(64), nullable=False),
        sa.Column("client_id", UUID, nullable=False),
        sa.Column("origin_warehouse_id", UUID, nullable=False),
        sa.Column("destination_warehouse_id", UUID, nullable=False),
        sa.Column("driver_id", UUID, nullable=True),
        sa.Column("vehicle_id", UUID, nullable=True),
        sa.Column("status", SHIPMENT_STATUS, nullable=False),
        sa.Column("weight_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("volume_m3", sa.Numeric(12, 3), nullable=False),
        sa.Column("pickup_at", TS, nullable=True),
        sa.Column("delivery_due_at", TS, nullable=True),
        sa.Column("delivered_at", TS, nullable=True),
        sa.Column("assigned_at", TS, nullable=True),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_shipments"),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name="fk_shipments_client_id_users", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["origin_warehouse_id"], ["warehouses.id"],
            name="fk_shipments_origin_warehouse_id_warehouses", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_warehouse_id"], ["warehouses.id"],
            name="fk_shipments_destination_warehouse_id_warehouses", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name="fk_shipments_driver_id_drivers", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], name="fk_shipments_vehicle_id_vehicles", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("reference_code", name="uq_shipments_reference_code"),
        sa.CheckConstraint("weight_kg > 0", name="ck_shipments_weight_positive"),
        sa.CheckConstraint("volume_m3 > 0", name="ck_shipments_volume_positive"),
    )

    # ----- shipment_tracking_events (append-only) -----
    op.create_table(
        "shipment_tracking_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("shipment_id", UUID, nullable=False),
        sa.Column("event_type", EVENT_TYPE, nullable=False),
        sa.Column("status", SHIPMENT_STATUS, nullable=True),
        sa.Column("event_time", TS, nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", UUID, nullable=True),
        sa.Column("evidence_url", sa.String(512), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_shipment_tracking_events"),
        sa.ForeignKeyConstraint(
            ["shipment_id"], ["shipments.id"],
            name="fk_shipment_tracking_events_shipment_id_shipments", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"], ["users.id"],
            name="fk_shipment_tracking_events_recorded_by_user_id_users", ondelete="SET NULL",
        ),
    )
    # Supports ordered history reads and the monotonic event_time guard.
    op.create_index(
        "ix_shipment_tracking_events_shipment_id_event_time",
        "shipment_tracking_events",
        ["shipment_id", "event_time"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shipment_tracking_events_shipment_id_event_time",
        table_name="shipment_tracking_events",
    )
    op.drop_table("shipment_tracking_events")
    op.drop_table("shipments")
    op.drop_table("vehicles")
    op.drop_table("drivers")
    op.drop_table("warehouses")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
