# ruff: noqa: E501 (long lines in test code)
"""The rule-reference migration (#321 momentum picks, simulation02): one additive step on simulation01.

It adds a nullable `rule_ref` to fills, exits and blocks, and a check on each: a momentum row names the rule that made the
pick, every other row names its horizon record and no rule. Runs in a private schema of the test database, rolled back at
the end, so nothing public is touched."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.db import models  # noqa: F401 - registers the mappers

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "alembic" / "versions"
TABLES = ("sim_fills", "sim_exits", "sim_blocks")


def _load(pattern: str, name: str):
    spec = importlib.util.spec_from_file_location(name, next(VERSIONS.glob(pattern)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def schema(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    name = "mig_simulation02_test"
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


def _upgrade_01(connection):
    _run(connection, _load("*_identity_phase1.py", "identity_for_02").upgrade)
    _run(connection, _load("*_horizon_records.py", "horizon_for_02").upgrade)
    _run(connection, _load("*_simulation_persistence.py", "simulation_for_02").upgrade)


def _upgrade_02(connection):
    _run(connection, _load("*_simulation_rule_ref.py", "simulation_rule_ref").upgrade)


def _columns(connection, name, table):
    return {c["name"]: c for c in inspect(connection).get_columns(table, schema=name)}


def test_it_chains_after_modswitch01_which_sits_on_simulation01():
    migration = _load("*_simulation_rule_ref.py", "rule_ref_chain")
    assert (migration.revision, migration.down_revision) == ("simulation02", "modswitch01")
    assert _load("*_module_switches.py", "modswitch_chain").down_revision == "simulation01"


def test_upgrade_adds_one_nullable_column_per_table_and_changes_no_row(schema):
    connection, name = schema
    _upgrade_01(connection)
    tables = set(inspect(connection).get_table_names(schema=name))
    before = {t: set(_columns(connection, name, t)) for t in TABLES}
    _upgrade_02(connection)
    assert set(inspect(connection).get_table_names(schema=name)) - tables == {
        "sim_not_ranked"
    }  # the one new table
    cols = _columns(connection, name, "sim_not_ranked")
    assert set(cols) == {"id", "run_id", "security_id", "reason"} and not any(
        cols[c]["nullable"] for c in ("run_id", "security_id", "reason")
    )
    for table in TABLES:
        built = _columns(connection, name, table)
        assert set(built) - before[table] == {"rule_ref"} and built["rule_ref"]["nullable"]
    runs = _columns(connection, name, "sim_runs")  # the run row also gets Momentum's declared universe
    assert {"momentum_universe", "momentum_universe_sha256"} <= set(runs)
    assert runs["momentum_universe"]["nullable"] and runs["momentum_universe_sha256"]["nullable"]


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
            "counts_in_comparison, rule_version, research_only) VALUES (1, 'syn-001', 'setup-01', 'momentum', 10000, 0, true, 'v', false)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO horizon_records (id, security_id, session_date, horizon_days, decision, reason, research_config_version, "
            "research_config_sha256, research_only) VALUES (1, 1, '2026-12-01', 5, 'TRADE', 'x', 'hz-rules-v1', 'abc', false)"
        )
    )


def _refused(connection, sql: str):
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError):
        connection.execute(text(sql))
    nested.rollback()


def test_the_database_refuses_a_row_that_traces_nowhere_or_to_the_wrong_thing(schema):
    connection, _ = schema
    _upgrade_01(connection)
    _seed(connection)
    _upgrade_02(connection)
    fill = "INSERT INTO sim_fills (portfolio_id, session_date, security_id, symbol, policy, horizon_record_id, rule_ref, rule_version, qty, price, charges, cost) VALUES (1, '2026-12-02', 1, 'X', '{policy}', {record}, {ref}, 'v', 1, 1, 0, 1)"
    ok = fill.format(policy="momentum", record="NULL", ref="'momentum-20d-top5:v1'")
    connection.execute(text(ok))
    connection.execute(
        text(fill.format(policy="model_only", record="1", ref="NULL").replace("'2026-12-02'", "'2026-12-03'"))
    )
    for policy, record, ref in (
        ("momentum", "NULL", "NULL"),  # momentum without a rule reference
        ("model_only", "NULL", "NULL"),  # a model row without a record
        ("brain_filtered", "NULL", "'momentum-20d-top5:v1'"),  # a rule reference where a record belongs
        ("model_only", "1", "'momentum-20d-top5:v1'"),  # both
    ):
        _refused(
            connection,
            fill.format(policy=policy, record=record, ref=ref).replace("'2026-12-02'", "'2026-12-04'"),
        )
    exit_ = "INSERT INTO sim_exits (portfolio_id, session_date, security_id, symbol, policy, horizon_record_id, rule_ref, rule_version, reason, qty, price, proceeds) VALUES (1, '2026-12-05', 1, 'X', '{policy}', {record}, {ref}, 'v', 'stop', 1, 1, 1)"
    connection.execute(text(exit_.format(policy="momentum", record="NULL", ref="'momentum-20d-top5:v1'")))
    _refused(
        connection, exit_.format(policy="momentum", record="NULL", ref="NULL").replace("'stop'", "'target'")
    )
    block = "INSERT INTO sim_blocks (portfolio_id, session_date, seq, security_id, symbol, policy, horizon_record_id, rule_ref, rule_version, reason) VALUES (1, '2026-12-05', {seq}, 1, 'X', '{policy}', {record}, {ref}, 'v', 'no_free_slot')"
    connection.execute(
        text(block.format(seq=0, policy="momentum", record="NULL", ref="'momentum-20d-top5:v1'"))
    )
    _refused(connection, block.format(seq=1, policy="model_only", record="NULL", ref="NULL"))


def test_downgrade_removes_only_the_column_and_the_check_and_up_down_up_works(schema):
    connection, name = schema
    _upgrade_01(connection)
    _upgrade_02(connection)
    migration = _load("*_simulation_rule_ref.py", "simulation_rule_ref_down")
    _run(connection, migration.downgrade)
    for table in TABLES:
        assert "rule_ref" not in _columns(connection, name, table)
    assert not {"momentum_universe", "momentum_universe_sha256"} & set(_columns(connection, name, "sim_runs"))
    assert "sim_not_ranked" not in set(inspect(connection).get_table_names(schema=name))
    checks = connection.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE conname LIKE 'ck_sim_%_trace' AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = :n)"
        ),
        {"n": name},
    ).all()
    assert checks == []
    _run(connection, migration.upgrade)
    assert all("rule_ref" in _columns(connection, name, table) for table in TABLES)
    assert "sim_not_ranked" in set(inspect(connection).get_table_names(schema=name))
