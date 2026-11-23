"""Index ``shipments.equipment_id``.

The ``Shipment`` model has declared ``equipment_id`` with ``index=True`` since the
equipment domain landed (0009), but no migration ever created the index, so
databases built from migrations lacked it while ``create_all`` databases had it
(``alembic check`` reported the drift). The column is a foreign key used by the
equipment ↔ shipment integration lookups.

Additive only: no data change. ``IF NOT EXISTS`` keeps it safe on databases that
were bootstrapped from model metadata and already carry the index.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0019_shipments_equipment_id_index"
down_revision: Union[str, None] = "0018_rls_policy_nullif_fail_closed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_shipments_equipment_id",
        "shipments",
        ["equipment_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_shipments_equipment_id", table_name="shipments", if_exists=True)
