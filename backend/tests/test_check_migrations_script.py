"""scripts/check_migrations.py: the schema comparison and its refusal to run on a non-test database."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_migrations.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("check_migrations", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identical_schemas_have_no_problems(script):
    schema = {"orders": {"id", "status"}, "positions": {"id"}}
    assert script.compare_schema(schema, {k: set(v) for k, v in schema.items()}) == []


def test_a_model_table_with_no_migration_fails(script):
    problems = script.compare_schema({"orders": {"id"}, "new_table": {"id"}}, {"orders": {"id"}})
    assert problems == ["model table 'new_table' is not created by any migration"]


def test_a_migration_table_no_model_defines_fails(script):
    problems = script.compare_schema({"orders": {"id"}}, {"orders": {"id"}, "ghost": {"id"}})
    assert problems == ["migrations create table 'ghost' that no model defines"]


def test_a_new_model_column_without_a_migration_fails(script):
    # Codex review finding 4: this used to pass because only table names were compared.
    problems = script.compare_schema({"orders": {"id", "idempotency_key"}}, {"orders": {"id"}})
    assert problems == ["model column 'orders.idempotency_key' is not created by any migration"]


def test_a_migration_column_the_model_forgot_fails(script):
    problems = script.compare_schema({"orders": {"id"}}, {"orders": {"id", "legacy"}})
    assert problems == ["migrations create column 'orders.legacy' that no model defines"]


def test_main_refuses_a_non_test_database_without_printing_the_url(script, monkeypatch, capsys):
    from swing_trade_ml.core import config

    monkeypatch.setattr(
        config.settings,
        "DATABASE_URL",
        "postgresql+psycopg://u:s3cretpw@localhost:5433/swing_trade_ml_migrate_test?host=db.example.com",
    )
    assert script.main() == 2
    err = capsys.readouterr().err
    assert "Refusing" in err
    assert "s3cretpw" not in err
    assert "db.example.com" not in err
