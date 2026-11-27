# ruff: noqa: E501 (long lines in test code)
"""The scan record tables (#260): scanrank01 (scan_runs) and scanrank02 (horizon_ranks).

Runs in a private schema of the test database (SET LOCAL search_path) on top of stand-ins for the two tables the new
ones point at, and is rolled back at the end, so nothing public is touched.
"""

from __future__ import annotations

import importlib.util
from datetime import date
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

RUN = (
    "INSERT INTO scan_runs (scan_key, session_date, horizon_days, pass_no, universe_count, scored_count, "
    "stale_count, missing_count, skipped_count) VALUES ('h5:2026-11-26', '2026-11-26', {h}, {p}, {u}, {s}, {st}, {m}, {k})"
)
RANK = (
    "INSERT INTO horizon_ranks (horizon_record_id, security_id, session_date, horizon_days, rank_no, cohort_size, "
    "rank_revision, source, scan_run_id) VALUES ({rec}, {sec}, '2026-11-26', {h}, {r}, {c}, {v}, '{src}', {run})"
)


def _run_sql(u=10, s=5, st=0, m=0, k=0, h=5, p=1):
    return RUN.format(h=h, p=p, u=u, s=s, st=st, m=m, k=k)


def _rank_sql(rec=1, sec=1, h=5, r=1, c=40, v=1, src="live", run="NULL"):
    return RANK.format(rec=rec, sec=sec, h=h, r=r, c=c, v=v, src=src, run=run)


def _load(pattern: str, name: str):
    spec = importlib.util.spec_from_file_location(name, next(VERSIONS.glob(pattern)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runs():
    return _load("*_scan_runs.py", "scan_runs_mig")


def _ranks():
    return _load("*_horizon_ranks.py", "horizon_ranks_mig")


@pytest.fixture()
def schema(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    name = "mig_scan_tables_test"
    connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    connection.execute(text(f'CREATE SCHEMA "{name}"'))
    connection.execute(text(f'SET LOCAL search_path TO "{name}"'))
    # Stand-ins for the two existing tables the new ones point at (both have BIGINT ids).
    connection.execute(text("CREATE TABLE securities (id bigserial primary key, status varchar(12))"))
    connection.execute(text("CREATE TABLE horizon_records (id bigserial primary key)"))
    connection.execute(text("INSERT INTO securities (id, status) VALUES (1, 'active')"))
    connection.execute(text("INSERT INTO horizon_records (id) VALUES (1)"))
    try:
        yield connection, name
    finally:
        transaction.rollback()
        connection.close()


def _run(connection, fn):
    with Operations.context(MigrationContext.configure(connection)):
        fn()


def _both(connection):
    _run(connection, _runs().upgrade)
    _run(connection, _ranks().upgrade)


def _tables(connection, name):
    return set(inspect(connection).get_table_names(schema=name))


def _functions(connection, name):
    return {
        r[0]
        for r in connection.execute(
            text(
                "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = :n"
            ),
            {"n": name},
        )
    }


def _refused(connection, statement, match=None):
    nested = connection.begin_nested()
    with pytest.raises(DBAPIError, match=match):
        connection.execute(text(statement))
    nested.rollback()


def test_chain_and_single_head():
    assert (_runs().revision, _runs().down_revision) == ("scanrank01", "signalkey01")
    assert (_ranks().revision, _ranks().down_revision) == ("scanrank02", "scanrank01")
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(config)
    (head,) = script.get_heads()  # exactly one head; later migrations may sit on top
    assert {"scanrank01", "scanrank02"} <= {r.revision for r in script.iterate_revisions(head, "base")}


def test_upgrade_adds_exactly_the_two_tables(schema):
    connection, name = schema
    before = _tables(connection, name)
    _run(connection, _runs().upgrade)
    assert _tables(connection, name) - before == {"scan_runs"}
    _run(connection, _ranks().upgrade)
    assert _tables(connection, name) - before == {"scan_runs", "horizon_ranks"}


def test_columns_match_the_models(schema):
    connection, name = schema
    _both(connection)
    for table in ("scan_runs", "horizon_ranks"):
        built = {c["name"] for c in inspect(connection).get_columns(table, schema=name)}
        assert built == {c.name for c in Base.metadata.tables[table].columns}


def test_not_null_columns_and_defaults(schema):
    connection, name = schema
    _both(connection)
    runs = {c["name"]: c for c in inspect(connection).get_columns("scan_runs", schema=name)}
    assert {c for c, v in runs.items() if not v["nullable"]} == {
        "id",
        "scan_key",
        "session_date",
        "horizon_days",
        "pass_no",
        "is_final",
        "universe_count",
        "scored_count",
        "stale_count",
        "missing_count",
        "skipped_count",
        "finished_at",
    }
    ranks = {c["name"]: c for c in inspect(connection).get_columns("horizon_ranks", schema=name)}
    assert {c for c, v in ranks.items() if v["nullable"]} == {"model_id", "scan_run_id"}
    connection.execute(text(_run_sql()))
    row = connection.execute(text("SELECT is_final, finished_at IS NOT NULL FROM scan_runs")).one()
    assert tuple(row) == (False, True)
    _refused(
        connection,
        "INSERT INTO scan_runs (scan_key, session_date, horizon_days) VALUES ('x', '2026-01-02', 5)",
    )


def test_scan_runs_constraints(schema):
    connection, _ = schema
    _both(connection)
    connection.execute(text(_run_sql(u=10, s=5, st=2, m=2, k=1)))  # sum == universe is allowed
    _refused(connection, _run_sql(u=10, s=5, st=2, m=2, k=2, p=2))  # sum above universe
    _refused(connection, _run_sql(s=-1, p=2))  # negative count
    _refused(connection, _run_sql(h=7, p=2))  # horizon not 5, 10 or 15
    _refused(connection, _run_sql(p=0))  # pass number below 1
    # the same (scan_key, horizon, pass) cannot be recorded twice
    _refused(connection, _run_sql(u=10, s=5, st=2, m=2, k=1), match="uq_scan_runs_key")
    connection.execute(text(_run_sql(h=10)))  # another horizon, same key and pass: fine


def test_horizon_ranks_constraints_and_foreign_keys(schema):
    connection, _ = schema
    _both(connection)
    connection.execute(text(_rank_sql(r=3, v=1)))
    connection.execute(text(_rank_sql(r=2, v=2, src="backfill")))  # the next revision is a new row
    _refused(connection, _rank_sql(r=3, v=1), match="uq_horizon_ranks_key")
    _refused(connection, _rank_sql(h=7, v=3))  # horizon
    _refused(connection, _rank_sql(r=0, v=3))  # rank 0 is never valid
    _refused(connection, _rank_sql(r=41, v=3))  # rank beyond the cohort
    _refused(connection, _rank_sql(v=0))  # revision
    _refused(connection, _rank_sql(v=3, src="guess"))  # source
    _refused(connection, _rank_sql(rec=99, v=3))  # unknown record
    _refused(connection, _rank_sql(sec=99, v=3))  # unknown stock
    _refused(connection, _rank_sql(run=99, v=3))  # unknown scan run


def test_foreign_keys_restrict_deletes(schema):
    connection, _ = schema
    _both(connection)
    connection.execute(text(_run_sql()))
    connection.execute(text(_rank_sql(run=1)))
    _refused(connection, "DELETE FROM horizon_records WHERE id = 1", match="horizon_ranks")
    _refused(connection, "DELETE FROM securities WHERE id = 1", match="horizon_ranks")


@pytest.mark.parametrize("table", ["scan_runs", "horizon_ranks"])
def test_triggers_refuse_update_delete_and_truncate(schema, table):
    connection, _ = schema
    _both(connection)
    connection.execute(text(_run_sql()))
    connection.execute(text(_rank_sql()))
    column = "universe_count" if table == "scan_runs" else "rank_no"
    for statement in (
        f"UPDATE {table} SET {column} = 2 WHERE id = 1",
        f"DELETE FROM {table} WHERE id = 1",
        f"TRUNCATE {table}",
    ):
        # scan_runs is also pointed at by horizon_ranks, so Postgres may refuse its TRUNCATE on the foreign key first.
        _refused(connection, statement, match="append-only|cannot truncate a table referenced")
    assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 1
    triggers = {
        r[0]
        for r in connection.execute(
            text("SELECT tgname FROM pg_trigger WHERE tgrelid = CAST(:t AS regclass) AND NOT tgisinternal"),
            {"t": table},
        )
    }
    assert triggers == {f"trg_{table}_no_update", f"trg_{table}_no_delete", f"trg_{table}_no_truncate"}


def test_downgrades_remove_only_what_they_added(schema):
    connection, name = schema
    _both(connection)
    _run(connection, _ranks().downgrade)
    assert _tables(connection, name) == {"securities", "horizon_records", "scan_runs"}
    assert "horizon_ranks_append_only" not in _functions(connection, name)
    assert "scan_runs_append_only" in _functions(connection, name)
    _run(connection, _runs().downgrade)
    assert _tables(connection, name) == {"securities", "horizon_records"}
    assert not {"scan_runs_append_only", "horizon_ranks_append_only"} & _functions(connection, name)


def test_up_down_up_works(schema):
    connection, name = schema
    _both(connection)
    _run(connection, _ranks().downgrade)
    _run(connection, _runs().downgrade)
    _both(connection)
    assert {"scan_runs", "horizon_ranks"} <= _tables(connection, name)


def test_neither_table_is_a_hypertable(schema):
    connection, _ = schema
    _both(connection)
    if not connection.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")).first():
        pytest.skip("timescaledb not installed in the test database")
    count = connection.execute(
        text(
            "SELECT count(*) FROM timescaledb_information.hypertables "
            "WHERE hypertable_name IN ('scan_runs','horizon_ranks')"
        )
    ).scalar_one()
    assert count == 0


def test_models_are_registered_and_round_trip(db_session):
    from swing_trade_ml.db.models.scan import HorizonRankRow, ScanRunRow

    assert {"scan_runs", "horizon_ranks"} <= set(Base.metadata.tables)
    run = ScanRunRow(
        scan_key="h5:2026-11-26",
        session_date=date(2026, 11, 26),
        horizon_days=5,
        universe_count=10,
        scored_count=8,
    )
    db_session.add(run)
    db_session.flush()
    assert (run.pass_no, run.is_final, run.stale_count) == (1, False, 0)
    assert run.finished_at is not None
    assert HorizonRankRow.__table__.c.horizon_record_id.foreign_keys
