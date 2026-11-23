# ruff: noqa: E501 (long lines in test code)
"""The horizon migration (#387): additive, matches the models, the trigger works, downgrade is clean, one head.

Runs in a private schema of the test database (SET LOCAL search_path) on top of the identity migration, and is rolled
back at the end, so nothing public is touched.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.db import models  # noqa: F401 - registers the mappers
from swing_trade_ml.db.base import Base

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "alembic" / "versions"
SIGNAL_COLUMNS = {"model_id", "model_version", "run_id"}


def _load(pattern: str, name: str):
    spec = importlib.util.spec_from_file_location(name, next(VERSIONS.glob(pattern)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def schema(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    name = "mig_horizon_test"
    connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    connection.execute(text(f'CREATE SCHEMA "{name}"'))
    connection.execute(text(f'SET LOCAL search_path TO "{name}"'))
    # The one existing table the migration alters. A stand-in with the old shape (no model, version or run column).
    connection.execute(text("CREATE TABLE signals (id bigserial primary key, price double precision)"))
    try:
        yield connection, name
    finally:
        transaction.rollback()
        connection.close()


def _run(connection, fn):
    with Operations.context(MigrationContext.configure(connection)):
        fn()


def _upgrade_both(connection):
    _run(connection, _load("*_identity_phase1.py", "identity_for_horizon").upgrade)
    _run(connection, _load("*_horizon_records.py", "horizon_migration").upgrade)


def _tables(connection, name):
    return set(inspect(connection).get_table_names(schema=name))


def test_it_chains_after_identity_and_is_the_only_head():
    migration = _load("*_horizon_records.py", "horizon_chain")
    assert (migration.revision, migration.down_revision) == ("horizon01", "identity01")
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == ["horizon01"]


def test_upgrade_from_empty_adds_one_table_and_three_nullable_signal_columns(schema):
    connection, name = schema
    _run(connection, _load("*_identity_phase1.py", "identity_for_horizon").upgrade)
    before = _tables(connection, name)
    connection.execute(text("INSERT INTO signals (price) VALUES (10.0)"))
    _run(connection, _load("*_horizon_records.py", "horizon_migration").upgrade)
    assert _tables(connection, name) - before == {"horizon_records"}
    columns = {c["name"]: c for c in inspect(connection).get_columns("signals", schema=name)}
    assert set(columns) >= SIGNAL_COLUMNS and all(columns[c]["nullable"] for c in SIGNAL_COLUMNS)
    # An old signal row stays unknown: nothing was filled in.
    row = connection.execute(text("SELECT model_id, model_version, run_id FROM signals")).one()
    assert tuple(row) == (None, None, None)


def test_the_migration_builds_the_columns_the_model_expects(schema):
    connection, name = schema
    _upgrade_both(connection)
    built = {c["name"] for c in inspect(connection).get_columns("horizon_records", schema=name)}
    assert built == {c.name for c in Base.metadata.tables["horizon_records"].columns}
    signal_built = {c["name"] for c in inspect(connection).get_columns("signals", schema=name)}
    assert signal_built >= SIGNAL_COLUMNS
    model_signal = {c.name for c in Base.metadata.tables["signals"].columns}
    assert model_signal >= SIGNAL_COLUMNS


def test_the_installed_trigger_refuses_update_delete_and_truncate(schema):
    connection, _ = schema
    _upgrade_both(connection)
    connection.execute(text("INSERT INTO securities (id, status) VALUES (1, 'active')"))
    connection.execute(
        text(
            "INSERT INTO horizon_records (id, security_id, session_date, horizon_days, decision, reason, "
            "research_config_version, research_config_sha256, research_only) "
            "VALUES (1, 1, '2026-01-02', 5, 'WAIT', 'x', 'hz-rules-v1', 'abc', false)"
        )
    )
    for statement in (
        "UPDATE horizon_records SET reason = 'y' WHERE id = 1",
        "DELETE FROM horizon_records WHERE id = 1",
        "TRUNCATE horizon_records",
    ):
        nested = connection.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text(statement))
        nested.rollback()


def test_the_database_refuses_a_horizon_that_is_not_5_10_or_15(schema):
    connection, _ = schema
    _upgrade_both(connection)
    connection.execute(text("INSERT INTO securities (id, status) VALUES (1, 'active')"))
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError):
        connection.execute(
            text(
                "INSERT INTO horizon_records (security_id, session_date, horizon_days, decision, reason, "
                "research_config_version, research_config_sha256, research_only) "
                "VALUES (1, '2026-01-02', 7, 'WAIT', 'x', 'hz-rules-v1', 'abc', false)"
            )
        )
    nested.rollback()


def test_downgrade_removes_only_what_it_added_and_identity_stays(schema):
    connection, name = schema
    _upgrade_both(connection)
    identity_tables = _tables(connection, name) - {"horizon_records", "signals"}
    _run(connection, _load("*_horizon_records.py", "horizon_migration").downgrade)
    tables = _tables(connection, name)
    assert "horizon_records" not in tables
    assert identity_tables <= tables and "signals" in tables
    assert {c["name"] for c in inspect(connection).get_columns("signals", schema=name)} == {"id", "price"}
    functions = {
        r[0]
        for r in connection.execute(
            text("SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = :n"),
            {"n": name},
        )
    }
    assert "horizon_records_append_only" not in functions and "score_ledger_append_only" in functions


def test_up_down_up_works(schema):
    connection, name = schema
    _upgrade_both(connection)
    horizon = _load("*_horizon_records.py", "horizon_migration")
    _run(connection, horizon.downgrade)
    _run(connection, horizon.upgrade)
    assert "horizon_records" in _tables(connection, name)
