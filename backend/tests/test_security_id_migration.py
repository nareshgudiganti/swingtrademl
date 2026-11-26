"""The nullable security_id columns (#389 decision 4): additive, nullable, FK + index, clean downgrade.

Runs in a private schema of the test database, rolled back at the end. The two old tables are
created minimally so existing rows can be checked to keep NULL.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from swing_trade_ml.db import models  # noqa: F401 - registers the mappers
from swing_trade_ml.db.base import Base

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
TABLES = ("instruments", "user_watchlist_items")


def _migration():
    path = next(VERSIONS.glob("*_security_id_columns.py"))
    spec = importlib.util.spec_from_file_location("security_id_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def schema(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    name = "mig_secid_test"
    connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    connection.execute(text(f'CREATE SCHEMA "{name}"'))
    connection.execute(text(f'SET LOCAL search_path TO "{name}"'))
    connection.execute(text("CREATE TABLE securities (id SERIAL PRIMARY KEY)"))
    for table in TABLES:
        connection.execute(text(f"CREATE TABLE {table} (id SERIAL PRIMARY KEY)"))
        connection.execute(text(f"INSERT INTO {table} DEFAULT VALUES"))
    try:
        yield connection, name
    finally:
        transaction.rollback()
        connection.close()


def _run(connection, fn):
    with Operations.context(MigrationContext.configure(connection)):
        fn()


def test_it_chains_after_signalkey01_with_its_own_revision():
    migration = _migration()
    assert migration.revision == "secid01" and migration.down_revision == "signalkey01"


def test_upgrade_adds_a_nullable_column_a_restrict_foreign_key_and_an_index(schema):
    connection, name = schema
    _run(connection, _migration().upgrade)
    inspector = inspect(connection)
    for table in TABLES:
        column = next(c for c in inspector.get_columns(table, schema=name) if c["name"] == "security_id")
        assert column["nullable"] is True
        (fk,) = [
            f
            for f in inspector.get_foreign_keys(table, schema=name)
            if f["constrained_columns"] == ["security_id"]
        ]
        assert fk["referred_table"] == "securities" and fk["referred_columns"] == ["id"]
        assert fk["options"].get("ondelete") == "RESTRICT"
        assert any(i["column_names"] == ["security_id"] for i in inspector.get_indexes(table, schema=name))


def test_existing_rows_keep_null_and_the_key_is_enforced(schema):
    connection, _ = schema
    _run(connection, _migration().upgrade)
    for table in TABLES:
        assert connection.execute(text(f"SELECT security_id FROM {table}")).scalar_one() is None
    connection.execute(text("INSERT INTO securities DEFAULT VALUES"))
    sid = connection.execute(text("SELECT id FROM securities")).scalar_one()
    connection.execute(text("UPDATE instruments SET security_id = :s"), {"s": sid})
    nested = connection.begin_nested()
    with pytest.raises(Exception, match=r"foreign key|violates"):
        connection.execute(text("DELETE FROM securities"))  # RESTRICT: still in use
    nested.rollback()


def test_downgrade_removes_the_columns_and_a_second_upgrade_works(schema):
    connection, name = schema
    migration = _migration()
    _run(connection, migration.upgrade)
    _run(connection, migration.downgrade)
    for table in TABLES:
        assert "security_id" not in {c["name"] for c in inspect(connection).get_columns(table, schema=name)}
    _run(connection, migration.upgrade)
    for table in TABLES:
        assert "security_id" in {c["name"] for c in inspect(connection).get_columns(table, schema=name)}


def test_the_models_declare_the_same_columns():
    for table in TABLES:
        column = Base.metadata.tables[table].columns["security_id"]
        assert column.nullable and column.index
        (fk,) = column.foreign_keys
        assert fk.column.table.name == "securities" and fk.ondelete == "RESTRICT"
