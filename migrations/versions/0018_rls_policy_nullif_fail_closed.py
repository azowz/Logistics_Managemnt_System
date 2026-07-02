"""Tenant RLS policy cleanup: fail closed on an *empty* ``app.current_tenant``.

Every tenant-scoped table carries the same ``tenant_isolation`` Row-Level
Security policy (shipped incrementally by migrations 0003, 0005-0007, 0009-0014,
0016). Each predicate casts the tenant GUC directly::

    current_setting('app.current_tenant', true)::uuid

``current_setting(..., true)`` returns SQL ``NULL`` when the GUC is *unset* — and
``NULL::uuid`` is ``NULL``, so an unset tenant already fails closed (sees no
rows). But when the GUC is set to the **empty string** ``''`` (a
``SET LOCAL app.current_tenant = ''`` / ``set_config(..., '', true)``),
``current_setting`` returns ``''`` and ``''::uuid`` raises
``invalid input syntax for type uuid: ""`` — the query *crashes* instead of
denying access. That is the known error the CI tenant-isolation gate surfaces.

This migration recreates every ``tenant_isolation`` policy with an
``NULLIF(current_setting('app.current_tenant', true), '')::uuid`` guard so the
empty string collapses to ``NULL`` and the policy fails closed exactly like the
unset case — no crash, no cross-tenant rows. Tenant access behaviour is
otherwise identical: a matching ``tenant_id`` still passes, and the platform
nil-UUID scope still sees all rows.

Purely a policy redefinition: no schema change, no data migration. RLS is
PostgreSQL-only, so the whole migration is a no-op on any other dialect (the
SQLite unit suite never creates these policies). The policy set is discovered
from ``pg_policies`` at run time, so it always matches whatever tenant tables
exist at head — the full expected set is the 49 tenant-scoped tables:

    users, warehouses, drivers, vehicles, shipments, shipment_tracking_events,
    event_store, dead_letter_events, audit_log, customers, orders, equipment,
    equipment_models, equipment_categories, operator_certifications,
    compliance_checks, axle_weight_profiles, escorts, permits, route_restrictions,
    liability_records, damage_reports, claims, coverage_rules, insurance_policies,
    quotes, invoices, invoice_lines, payments, settlements, payouts, penalties,
    notification_templates, notifications, notification_delivery_attempts,
    proj_shipment_performance, proj_financial_summary, proj_ar_aging,
    proj_claims_metrics, proj_compliance_metrics, proj_notification_deliverability,
    proj_operations_dashboard, projection_health, integration_partners,
    partner_api_keys, webhook_subscriptions, webhook_deliveries,
    webhook_delivery_attempts, inbound_integration_events.

Revision ID: 0018_rls_policy_nullif_fail_closed
Revises: 0017_integration_delivery_worker_hardening
Create Date: 2026-07-02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_rls_policy_nullif_fail_closed"
down_revision: Union[str, None] = "0017_integration_delivery_worker_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NIL = "00000000-0000-0000-0000-000000000000"
_POLICY = "tenant_isolation"

# The original (pre-0018) predicate: a bare cast that crashes on an empty GUC.
_OLD_TENANT_EXPR = "current_setting('app.current_tenant', true)::uuid"
# The fail-closed predicate: empty string -> NULL -> denies, never crashes.
_NEW_TENANT_EXPR = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def _is_postgres() -> bool:
    """True when the migration runs against PostgreSQL (RLS is PG-only)."""
    return op.get_context().dialect.name == "postgresql"


def _policy_body(tenant_expr: str) -> str:
    """USING/WITH CHECK clauses for the tenant-isolation policy.

    Identical to every shipped policy except for ``tenant_expr`` (the GUC read),
    which lets upgrade/downgrade swap the NULLIF guard in and out while keeping
    the access semantics — own tenant, or the platform nil-UUID scope — intact.
    """
    predicate = f"tenant_id = {tenant_expr} OR {tenant_expr} = '{NIL}'::uuid"
    return f"USING ({predicate}) WITH CHECK ({predicate})"


def _recreate_all_policies(tenant_expr: str) -> None:
    """Drop and recreate every ``tenant_isolation`` policy with ``tenant_expr``.

    The set of target tables is read from ``pg_policies`` so it tracks whatever
    tenant tables exist at head, rather than a hand-maintained list that could
    drift from the incremental domain migrations that created the policies.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT schemaname, tablename FROM pg_policies "
            "WHERE policyname = :policy ORDER BY schemaname, tablename"
        ),
        {"policy": _POLICY},
    ).fetchall()
    body = _policy_body(tenant_expr)
    for schema, table in rows:
        qualified = f'"{schema}"."{table}"'
        op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {qualified}")
        op.execute(f"CREATE POLICY {_POLICY} ON {qualified} {body}")


def upgrade() -> None:
    if _is_postgres():
        _recreate_all_policies(_NEW_TENANT_EXPR)


def downgrade() -> None:
    if _is_postgres():
        _recreate_all_policies(_OLD_TENANT_EXPR)
