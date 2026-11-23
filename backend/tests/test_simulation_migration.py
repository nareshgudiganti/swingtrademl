# ruff: noqa: E501 (long lines in test code)
"""The simulation persistence migration (#321): one additive step after horizon01, matches the models, the database
itself refuses negative cash, a non-synthetic row, a duplicate fill and a second validation portfolio, the downgrade
removes only what it added, and up-down-up works.

Runs in a private schema of the test database (SET LOCAL search_path) on top of the identity and horizon migrations and
is rolled back at the end, so nothing public is touched and no other database is involved."""

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
from swing_trade_ml.db.models.simulation import SIM_TABLES

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "alembic" / "versions"


def _load(pattern: str, name: str):
    spec = importlib.util.spec_from_file_location(name, next(VERSIONS.glob(pattern)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def schema(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    name = "mig_simulation_test"
    connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    connection.execute(text(f'CREATE SCHEMA "{name}"'))
    connection.execute(text(f'SET LOCAL search_path TO "{name}"'))
    connection.execute(text("CREATE TABLE signals (id bigserial primary key, price double precision)"))
    try:
        yield connection, name
    finally:
        transaction.rollback()
        connection.close()


def _run(connection, fn):
    with Operations.context(MigrationContext.configure(connection)):
        fn()


def _upgrade_to_horizon(connection):
    _run(connection, _load("*_identity_phase1.py", "identity_for_sim").upgrade)
    _run(connection, _load("*_horizon_records.py", "horizon_for_sim").upgrade)


def _upgrade_all(connection):
    _upgrade_to_horizon(connection)
    _run(connection, _load("*_simulation_persistence.py", "simulation_migration").upgrade)


def _tables(connection, name):
    return set(inspect(connection).get_table_names(schema=name))


def test_it_chains_after_horizon_and_the_signal_key_migration_is_the_only_head():
    migration = _load("*_simulation_persistence.py", "simulation_chain")
    assert (migration.revision, migration.down_revision) == ("simulation01", "horizon01")
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    # the module switches (#291) and the signal key (#360) sit on top of it; it stays the one chain, with one head
    assert ScriptDirectory.from_config(config).get_heads() == ["signalkey01"]


def test_upgrade_adds_exactly_the_eight_simulation_tables_and_changes_nothing_else(schema):
    connection, name = schema
    _upgrade_to_horizon(connection)
    before = _tables(connection, name)
    signal_columns = {c["name"] for c in inspect(connection).get_columns("signals", schema=name)}
    connection.execute(text("INSERT INTO signals (price) VALUES (10.0)"))
    _run(connection, _load("*_simulation_persistence.py", "simulation_migration").upgrade)
    assert _tables(connection, name) - before == set(SIM_TABLES) and before <= _tables(connection, name)
    assert {c["name"] for c in inspect(connection).get_columns("signals", schema=name)} == signal_columns
    assert connection.execute(text("SELECT count(*) FROM signals")).scalar() == 1


def test_the_migration_builds_the_columns_the_models_expect(schema):
    connection, name = schema
    _upgrade_all(connection)
    for table in SIM_TABLES:
        built = {c["name"]: c for c in inspect(connection).get_columns(table, schema=name)}
        model = Base.metadata.tables[table]
        assert set(built) == {c.name for c in model.columns}, table
        for column in model.columns:
            assert built[column.name]["nullable"] == column.nullable or column.primary_key, (
                table,
                column.name,
            )
        assert not {"user_id", "account_id", "email"} & set(built)


def _seed(connection):
    connection.execute(text("INSERT INTO securities (id, status) VALUES (1, 'active')"))
    connection.execute(
        text(
            "INSERT INTO sim_runs (id, run_key, rule_version, research_config_version, research_only, horizon_days) "
            "VALUES (1, 'r', 'hz-rules-v1:5D', 'hz-rules-v1', false, 5)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO sim_portfolios (run_id, persona_key, setup_key, policy, balance_inr, start_offset, "
            "counts_in_comparison, rule_version, research_only) VALUES (1, 'syn-001', 'setup-01', 'model_only', "
            "10000, 0, true, 'hz-rules-v1:5D', false)"
        )
    )


def _refused(connection, sql: str):
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError):
        connection.execute(text(sql))
    nested.rollback()


def test_the_database_itself_refuses_the_bad_rows(schema):
    connection, _ = schema
    _upgrade_all(connection)
    _seed(connection)
    day = "INSERT INTO sim_days (portfolio_id, session_date, cash, equity, halted, rule_version, research_only) VALUES (1, '2026-12-01', {cash}, 10000, false, 'v', false)"
    connection.execute(text(day.format(cash=100)))
    _refused(connection, day.format(cash=100))  # the same portfolio and session twice
    _refused(connection, day.replace("2026-12-01", "2026-12-02").format(cash=-0.01))  # negative cash
    fill = "INSERT INTO sim_fills (portfolio_id, session_date, security_id, symbol, policy, rule_version, qty, price, charges, cost) VALUES (1, '2026-12-01', 1, 'X', 'model_only', 'v', {qty}, 1, 0, 1)"
    connection.execute(text(fill.format(qty=1)))
    _refused(connection, fill.format(qty=1))  # the same fill twice
    _refused(connection, fill.replace("'2026-12-01'", "'2026-12-02'").format(qty=0))  # no shares
    _refused(
        connection,
        fill.replace("'2026-12-01'", "'2026-12-02'").replace("'model_only'", "'guess'").format(qty=1),
    )
    _refused(
        connection,
        "INSERT INTO sim_runs (run_key, rule_version, research_config_version, research_only, horizon_days, synthetic) VALUES ('s','v','c',false,5,false)",
    )
    _refused(
        connection,
        "INSERT INTO sim_runs (run_key, rule_version, research_config_version, research_only, horizon_days) VALUES ('h','v','c',false,7)",
    )
    validation = "INSERT INTO sim_portfolios (run_id, persona_key, setup_key, policy, balance_inr, start_offset, counts_in_comparison, rule_version, research_only) VALUES (1, '{key}', 'setup-01', 'momentum', 10000, 0, false, 'v', false)"
    connection.execute(text(validation.format(key="syn-100")))
    _refused(connection, validation.format(key="syn-099"))  # a second validation portfolio in one run
    _refused(
        connection,
        "INSERT INTO sim_fills (portfolio_id, session_date, security_id, symbol, policy, rule_version, qty, price, charges, cost) VALUES (1, '2026-12-03', 99, 'X', 'model_only', 'v', 1, 1, 0, 1)",
    )  # no such stock
    _refused(
        connection,
        "INSERT INTO sim_fills (portfolio_id, session_date, security_id, symbol, horizon_record_id, policy, rule_version, qty, price, charges, cost) VALUES (1, '2026-12-03', 1, 'X', 99, 'model_only', 'v', 1, 1, 0, 1)",
    )  # no such record


def test_downgrade_removes_only_the_eight_tables_and_horizon_stays(schema):
    connection, name = schema
    _upgrade_all(connection)
    kept = _tables(connection, name) - set(SIM_TABLES)
    _run(connection, _load("*_simulation_persistence.py", "simulation_migration").downgrade)
    after = _tables(connection, name)
    assert (
        after == kept and "horizon_records" in after and "securities" in after and not set(SIM_TABLES) & after
    )


def test_up_down_up_works(schema):
    connection, name = schema
    _upgrade_all(connection)
    migration = _load("*_simulation_persistence.py", "simulation_migration")
    _run(connection, migration.downgrade)
    _run(connection, migration.upgrade)
    assert set(SIM_TABLES) <= _tables(connection, name)
