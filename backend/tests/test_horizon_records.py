# ruff: noqa: E501 (long lines in test code)
"""Horizon recommendation records on the stock identity (#387): write-once, revisions append, research-only gate.

Uses the identity service (`resolve`, `ensure_for_instrument`) as the only way to name a stock.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import date, timedelta
from functools import partial
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.brain.horizons import HorizonStore, ModelOutput
from swing_trade_ml.brain.horizons import run_all_horizons as _run_all_horizons
from swing_trade_ml.brain.horizons import run_horizon as _run_horizon
from swing_trade_ml.core import research_config
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.services import horizon_records as hr
from swing_trade_ml.services.identity import writer

run_horizon = partial(_run_horizon, research_caller=True)  # 10D and 15D records are research records
run_all_horizons = partial(_run_all_horizons, research_caller=True)
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
SESSION = date(2026, 1, 2)
SESSIONS = tuple(d for i in range(40) if (d := SESSION + timedelta(days=i)).weekday() < 5)
_tokens = iter(range(387_100, 387_900))


def _security(db, symbol: str) -> int:
    row = Instrument(
        instrument_token=next(_tokens), tradingsymbol=symbol, exchange="NSE", instrument_type="EQ", is_active=True
    )
    db.add(row)
    db.flush()
    return writer.ensure_for_instrument(db, row)


def _out(symbol: str, horizon: int, score: float = 0.9, version: str | None = None) -> ModelOutput:
    return ModelOutput(
        model_name=f"synthetic_h{horizon}",
        model_version=version or f"v{horizon}.1",
        forecast_horizon_sessions=horizon,
        role="final",
        symbol=symbol,
        input_session=SESSION,
        input_close=100.0,
        score=score,
    )


def _record(symbol: str, horizon: int = 5, score: float = 0.9, version: str | None = None):
    return run_horizon(horizon, [_out(symbol, horizon, score, version)], SESSION, SESSIONS, symbol=symbol)


def _rows(db, security_id: int) -> list[HorizonRecordRow]:
    db.expire_all()
    return list(
        db.scalars(
            select(HorizonRecordRow).where(HorizonRecordRow.security_id == security_id).order_by(HorizonRecordRow.id)
        )
    )


def test_a_first_write_is_revision_one_and_carries_the_config_version(db_session):
    sid = _security(db_session, "HZ387A")
    result = hr.save_record(db_session, _record("HZ387A"), security_id=sid, model_id=7)
    assert (result.revision, result.created) == (1, True)
    (row,) = _rows(db_session, sid)
    assert (row.horizon_days, row.model_id, row.model_version, row.decision) == (5, 7, "v5.1", "TRADE")
    cfg = research_config.active()
    assert (row.research_config_version, row.research_config_sha256) == (cfg.version, cfg.sha256)
    assert row.session_date == SESSION and row.evaluation_due_session == SESSIONS[5]
    assert row.supersedes_id is None


def test_a_retry_adds_nothing(db_session):
    sid = _security(db_session, "HZ387B")
    first = hr.save_record(db_session, _record("HZ387B"), security_id=sid, model_id=7)
    again = hr.save_record(db_session, _record("HZ387B"), security_id=sid, model_id=7)
    assert (again.created, again.row_id, again.revision) == (False, first.row_id, 1)
    assert len(_rows(db_session, sid)) == 1


def test_a_different_result_appends_the_next_revision_and_keeps_the_first(db_session):
    sid = _security(db_session, "HZ387C")
    first = hr.save_record(db_session, _record("HZ387C", score=0.90), security_id=sid, model_id=7)
    second = hr.save_record(db_session, _record("HZ387C", score=0.65), security_id=sid, model_id=7)
    assert (second.created, second.revision) == (True, 2)
    rows = _rows(db_session, sid)
    assert [(r.revision, r.decision, r.score) for r in rows] == [(1, "TRADE", 0.90), (2, "WATCH", 0.65)]
    assert rows[1].supersedes_id == first.row_id
    assert [r.revision for r in hr.records_for(db_session, sid, view="first")] == [1]
    assert [r.revision for r in hr.records_for(db_session, sid, view="latest")] == [2]
    assert [r.revision for r in hr.records_for(db_session, sid, view="all")] == [1, 2]


def test_a_new_model_version_is_its_own_line_not_a_revision(db_session):
    sid = _security(db_session, "HZ387D")
    hr.save_record(db_session, _record("HZ387D", version="v1"), security_id=sid, model_id=7)
    hr.save_record(db_session, _record("HZ387D", version="v2"), security_id=sid, model_id=8)
    assert [(r.model_version, r.revision) for r in _rows(db_session, sid)] == [("v1", 1), ("v2", 1)]


def test_a_no_decision_record_has_no_model_and_a_retry_still_adds_nothing(db_session):
    sid = _security(db_session, "HZ387E")
    none = run_horizon(5, [], SESSION, SESSIONS, symbol="HZ387E")
    assert none.decision == "NO_DECISION"
    hr.save_record(db_session, none, security_id=sid)
    hr.save_record(db_session, none, security_id=sid)
    (row,) = _rows(db_session, sid)
    assert (row.model_id, row.model_version, row.revision) == (None, "", 1)


def test_five_ten_and_fifteen_are_three_independent_lines_and_only_five_is_product(db_session):
    sid = _security(db_session, "HZ387F")
    outputs = [_out("HZ387F", h) for h in (5, 10, 15)]
    results = run_all_horizons(SESSION, outputs, SESSIONS, HorizonStore(), symbol="HZ387F")
    for h, record in results.items():
        hr.save_record(db_session, record, security_id=sid, model_id=h)
    rows = _rows(db_session, sid)
    assert [(r.horizon_days, r.research_only) for r in rows] == [(5, False), (10, True), (15, True)]
    assert [r.horizon_days for r in hr.product_records(db_session, sid)] == [5]
    assert [r.horizon_days for r in hr.records_for(db_session, sid, horizon_days=15)] == [15]


def test_research_only_comes_from_the_config_never_from_the_caller(db_session):
    sid = _security(db_session, "HZ387G")
    record = replace(_record("HZ387G", horizon=10), decision="TRADE")
    hr.save_record(db_session, record, security_id=sid, model_id=1)
    (row,) = _rows(db_session, sid)
    assert row.research_only is True
    import inspect

    assert "research_only" not in inspect.signature(hr.save_record).parameters


def test_an_unknown_stock_is_refused_and_nothing_is_written(db_session):
    before = len(list(db_session.scalars(select(HorizonRecordRow))))
    with pytest.raises(hr.UnknownSecurityError):
        hr.save_for_symbol(db_session, _record("NOSUCHSTOCK387"))
    assert len(list(db_session.scalars(select(HorizonRecordRow)))) == before


def test_a_known_stock_is_resolved_by_the_identity_service(db_session):
    sid = _security(db_session, "HZ387H")
    result = hr.save_for_symbol(db_session, _record("HZ387H"), model_id=3)
    assert _rows(db_session, sid)[0].id == result.row_id


def test_an_unsupported_horizon_is_an_error_never_a_guess(db_session):
    sid = _security(db_session, "HZ387I")
    bad = replace(_record("HZ387I"), decision_horizon=7)
    with pytest.raises(research_config.ResearchConfigError):
        hr.save_record(db_session, bad, security_id=sid)


def test_the_database_refuses_update_delete_and_truncate(db_session):
    migration = _migration()
    migration.install_triggers(db_session.connection())
    sid = _security(db_session, "HZ387J")
    row = hr.save_record(db_session, _record("HZ387J"), security_id=sid, model_id=1)
    for statement in (
        f"UPDATE horizon_records SET score = 0.1 WHERE id = {row.row_id}",
        f"DELETE FROM horizon_records WHERE id = {row.row_id}",
        "TRUNCATE horizon_records",
    ):
        nested = db_session.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            db_session.execute(text(statement))
        nested.rollback()
    assert _rows(db_session, sid)[0].score == 0.9


def test_the_unique_key_stops_a_second_row_for_the_same_revision(db_session):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    sid = _security(db_session, "HZ387K")
    hr.save_record(db_session, _record("HZ387K"), security_id=sid, model_id=1)
    (row,) = _rows(db_session, sid)
    values = {c.name: getattr(row, c.name) for c in HorizonRecordRow.__table__.columns if c.name != "id"}
    got = db_session.execute(pg_insert(HorizonRecordRow).values(**values).on_conflict_do_nothing().returning(HorizonRecordRow.id))
    assert got.scalar_one_or_none() is None
    assert len(_rows(db_session, sid)) == 1


def test_a_signal_has_no_model_or_run_until_a_writer_sets_them(db_session):
    sid = _security(db_session, "HZ387L")
    inst = db_session.scalar(select(Instrument).where(Instrument.tradingsymbol == "HZ387L"))
    strategy = Strategy(name="hz387-strategy", strategy_type="ml_swing")
    db_session.add(strategy)
    db_session.flush()
    from datetime import UTC, datetime

    sig = Signal(strategy_id=strategy.id, instrument_id=inst.id, price=10.0, generated_at=datetime.now(UTC))
    db_session.add(sig)
    db_session.flush()
    db_session.refresh(sig)
    assert (sig.model_id, sig.model_version, sig.run_id) == (None, None, None)
    sig.model_id, sig.model_version, sig.run_id = 5, "v2", "run-1"
    db_session.flush()
    assert (sig.model_id, sig.model_version, sig.run_id) == (5, "v2", "run-1")
    assert sid


def _migration():
    path = next(VERSIONS.glob("*_horizon_records.py"))
    spec = importlib.util.spec_from_file_location("horizon_records_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
