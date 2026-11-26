"""The identity migration (#389 S1/S2): additive, matches the models, the trigger works, downgrade is clean.

It runs in a private schema of the test database (SET LOCAL search_path), so nothing public is touched and the
whole thing is rolled back at the end.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.db import models  # noqa: F401 - registers the mappers
from swing_trade_ml.db.base import Base

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
NEW_TABLES = ("securities", "security_symbols", "security_aliases", "score_ledger")


def _migration():
    path = next(VERSIONS.glob("*_identity_phase1.py"))
    spec = importlib.util.spec_from_file_location("identity_phase1_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def schema(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    name = "mig_identity_test"
    connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    connection.execute(text(f'CREATE SCHEMA "{name}"'))
    connection.execute(text(f'SET LOCAL search_path TO "{name}"'))
    try:
        yield connection, name
    finally:
        transaction.rollback()
        connection.close()


def _run(connection, fn):
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        fn()


def _tables(connection, schema_name):
    return set(inspect(connection).get_table_names(schema=schema_name))


def test_upgrade_creates_exactly_the_new_tables_and_nothing_else(schema):
    connection, name = schema
    migration = _migration()
    assert _tables(connection, name) == set()
    _run(connection, migration.upgrade)
    assert _tables(connection, name) == set(NEW_TABLES)


def test_the_migration_builds_the_columns_the_models_expect(schema):
    connection, name = schema
    _run(connection, _migration().upgrade)
    inspector = inspect(connection)
    for table in NEW_TABLES:
        built = {c["name"] for c in inspector.get_columns(table, schema=name)}
        expected = {c.name for c in Base.metadata.tables[table].columns}
        assert built == expected, (table, built ^ expected)


def test_it_chains_after_the_current_head_with_its_own_revision():
    migration = _migration()
    assert migration.revision == "identity01" and migration.down_revision == "wlsales01"


def test_the_ledger_trigger_refuses_update_delete_and_truncate(schema):
    connection, _ = schema
    _run(connection, _migration().upgrade)
    connection.execute(text("INSERT INTO securities (id, name) VALUES (1, 'T')"))
    connection.execute(
        text(
            "INSERT INTO score_ledger (id, security_id, session_date, source, score) "
            "VALUES (1, 1, '2026-11-20', 'v1_scan', 0.9)"
        )
    )
    for statement in (
        "UPDATE score_ledger SET score = 0.5 WHERE id = 1",
        "DELETE FROM score_ledger WHERE id = 1",
        "TRUNCATE score_ledger",
    ):
        nested = connection.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text(statement))
        nested.rollback()
    assert connection.execute(text("SELECT score FROM score_ledger WHERE id = 1")).scalar_one() == 0.9


def test_the_ledger_key_allows_one_row_per_revision_and_treats_a_missing_horizon_as_one_value(schema):
    connection, _ = schema
    _run(connection, _migration().upgrade)
    connection.execute(text("INSERT INTO securities (id) VALUES (1)"))
    insert = (
        "INSERT INTO score_ledger (security_id, session_date, horizon_days, source, model_name, "
        "model_version, revision) VALUES (1, '2026-11-20', {h}, 'v1_scan', 'm', 'v1', {r})"
    )
    connection.execute(text(insert.format(h="NULL", r=1)))
    connection.execute(text(insert.format(h="NULL", r=2)))  # a new revision is fine
    for h in ("NULL", "5"):
        connection.execute(text(insert.format(h=h, r=3)))
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError):  # the same key twice: NULL horizon is one value, not "always different"
        connection.execute(text(insert.format(h="NULL", r=1)))
    nested.rollback()


def test_downgrade_drops_what_upgrade_made_and_a_second_upgrade_works(schema):
    connection, name = schema
    migration = _migration()
    _run(connection, migration.upgrade)
    _run(connection, migration.downgrade)
    assert _tables(connection, name) == set()
    functions = connection.execute(
        text("SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
             "WHERE p.proname = 'score_ledger_append_only' AND n.nspname = :s"),
        {"s": name},
    ).all()
    assert functions == []
    _run(connection, migration.upgrade)
    assert _tables(connection, name) == set(NEW_TABLES)
