"""Compile the schema migrations using PostgreSQL's real identifier limits."""

from __future__ import annotations

import io
import re
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core import config as settings_module


def test_schema_migrations_compile_for_postgresql(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    settings = settings_module.Settings(
        _env_file=None,
        database_url="postgresql+psycopg2://test:test@localhost/unused",
        secret_key="migration-test-secret-key-at-least-32-characters",
    )
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    sql = io.StringIO()
    config = Config(str(root / "alembic.ini"), output_buffer=sql)
    config.set_main_option("script_location", str(root / "migrations"))

    # 0018 queries pg_policies at runtime; 0017 is the last schema-changing revision.
    command.upgrade(config, "0017_integration_delivery_worker_hardening", sql=True)

    generated = sql.getvalue()
    constraint = re.search(
        r"CONSTRAINT (fk_operator_certifications_equipment_category_id_\w+) FOREIGN KEY",
        generated,
    )
    assert constraint is not None
    assert len(constraint.group(1)) <= 63
    assert "CREATE TABLE webhook_deliveries" in generated
    widen = "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"
    record_revision = (
        "UPDATE alembic_version SET version_num='0013_notifications_communications_domain'"
    )
    assert generated.index(widen) < generated.index(record_revision)
