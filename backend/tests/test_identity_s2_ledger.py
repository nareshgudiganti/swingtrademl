# ruff: noqa: E501 (long lines in test code)
"""#389 step S2: the append-only score ledger and the score_history hook (IDENTITY-CONTRACTS.md section 4).

Developer-1's proof tests (test/389-identity-defects) are ported here with the ledger as the place that keeps the
evidence: the old `stock_score_history` table keeps its one-row-per-day behaviour for the screens, the ledger keeps
every score once, with its session date, horizon, model and version.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.identity import ScoreLedger
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.trading import StockScore
from swing_trade_ml.services import score_history
from swing_trade_ml.services.identity import ledger, resolve, writer

_tokens = iter(range(389_600, 389_990))
MODEL = "swing_classifier:v2"
EXIT = 0.4
FRIDAY = date(2026, 11, 20)
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _instrument(db, symbol: str) -> Instrument:
    row = Instrument(
        instrument_token=next(_tokens), tradingsymbol=symbol, exchange="NSE", instrument_type="EQ", is_active=True
    )
    db.add(row)
    db.flush()
    return row


def _security(db, symbol: str) -> int:
    return writer.ensure_for_instrument(db, _instrument(db, symbol))


def _rows(db, security_id: int) -> list[ScoreLedger]:
    db.expire_all()
    return list(db.scalars(select(ScoreLedger).where(ScoreLedger.security_id == security_id).order_by(ScoreLedger.id)))


def _record(db, inst, score, *, today=None, model=MODEL):
    return score_history.record_stock_scores(db, [(inst.id, score, model)], EXIT, today=today)


def _candle(db, inst, day: date) -> None:
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime(day.year, day.month, day.day, tzinfo=IST).astimezone(UTC),
            open=100.0, high=101.0, low=99.0, close=100.5, volume=1000,
        )
    )
    db.flush()


class _Clock(datetime):
    fixed: datetime

    @classmethod
    def now(cls, tz=None):
        return cls.fixed.astimezone(tz) if tz else cls.fixed


def _at(monkeypatch, when: datetime) -> None:
    _Clock.fixed = when
    monkeypatch.setattr(score_history, "datetime", _Clock)


# ------------------------------------------------------------------------------ the ledger itself


def test_the_same_score_twice_is_one_row_and_a_changed_one_is_the_next_revision(db_session):
    sid = _security(db_session, "LED389A")
    first = ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.9)
    again = ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.9)
    assert first.created and first.revision == 1
    assert not again.created and again.row_id == first.row_id
    changed = ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.5)
    assert changed.created and changed.revision == 2
    rows = _rows(db_session, sid)
    assert [(r.revision, r.score) for r in rows] == [(1, 0.9), (2, 0.5)]
    assert rows[1].supersedes_id == rows[0].id


def test_first_and_latest_views_differ_and_are_labelled_by_the_caller(db_session):
    sid = _security(db_session, "LED389B")
    for score in (0.9, 0.5, 0.7):
        ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=score)
    assert [r.score for r in ledger.history(db_session, sid, view="first")] == [0.9]
    assert [r.score for r in ledger.history(db_session, sid, view="latest")] == [0.7]
    assert [r.score for r in ledger.history(db_session, sid, view="all")] == [0.9, 0.5, 0.7]


def test_the_ninety_fifty_eighty_sequence_is_three_rows_in_order_for_a_stock_outside_the_top_five(db_session):
    sid = _security(db_session, "PAYTM389")
    for day, score in ((date(2026, 11, 16), 0.90), (date(2026, 11, 17), 0.50), (date(2026, 11, 18), 0.80)):
        ledger.append_score(db_session, security_id=sid, session_date=day, source="v1_scan", score=score)
    got = ledger.history(db_session, sid)
    assert [(r.session_date.day, r.score) for r in got] == [(16, 0.90), (17, 0.50), (18, 0.80)]


def test_a_gap_is_a_missing_row_never_a_zero_and_a_later_score_is_a_new_revision(db_session):
    sid = _security(db_session, "GAP389")
    gap = ledger.append_missing(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", reason="no candle")
    assert gap.created
    (row,) = _rows(db_session, sid)
    assert row.status == "missing" and row.score is None and row.note == "no candle"
    assert not ledger.append_missing(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", reason="no candle").created
    late = ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.6)
    assert late.created and late.revision == 2
    with pytest.raises(ValueError):
        ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=None)


def test_missing_rows_are_written_for_every_stock_the_scan_was_meant_to_cover(db_session):
    a, b, c = (_security(db_session, f"UNI389{x}") for x in "ABC")
    written = ledger.append_missing_for_universe(
        db_session, session_date=FRIDAY, universe_security_ids=[a, b, c], scored_security_ids=[a], source="v1_scan"
    )
    assert written == 2
    assert [r.status for r in _rows(db_session, b)] == ["missing"] and _rows(db_session, a) == []
    again = ledger.append_missing_for_universe(
        db_session, session_date=FRIDAY, universe_security_ids=[a, b, c], scored_security_ids=[a], source="v1_scan"
    )
    assert again == 0


def test_a_lost_race_re_reads_and_records_nothing_twice(db_session, monkeypatch):
    """Two writers: the second one read before the first one wrote. The unique key refuses a duplicate row, and
    the second one looks again and finds the same value already there."""
    sid = _security(db_session, "RACE389")
    ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.9)
    real = ledger._latest
    calls = {"n": 0}

    def stale_first(*args, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*args, **kwargs)

    monkeypatch.setattr(ledger, "_latest", stale_first)
    result = ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.9)
    assert not result.created and len(_rows(db_session, sid)) == 1


def test_horizons_and_models_are_separate_lines_for_one_stock(db_session):
    sid = _security(db_session, "LANES389")
    for horizon in (5, 10, 15, None):
        ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.5, horizon_days=horizon, model_name="m", model_version="v1")
    ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.5, horizon_days=5, model_name="m", model_version="v2")
    assert len(_rows(db_session, sid)) == 5
    assert len(ledger.history(db_session, sid, horizon_days=5)) == 2


def test_unknown_status_and_source_are_refused(db_session):
    sid = _security(db_session, "BAD389")
    with pytest.raises(ValueError):
        ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="nope", score=0.5)
    with pytest.raises(ValueError):
        ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.5, status="weird")


def test_the_ledger_trigger_refuses_update_delete_and_truncate_in_the_database(db_session):
    """The same installer the migration uses (as the lane tests do)."""
    path = next(VERSIONS.glob("*_identity_phase1.py"))
    spec = importlib.util.spec_from_file_location("identity_phase1_trigger_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install_triggers(db_session.connection())
    sid = _security(db_session, "TRG389")
    row = ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.9)
    for statement in (
        f"UPDATE score_ledger SET score = 0.1 WHERE id = {row.row_id}",
        f"DELETE FROM score_ledger WHERE id = {row.row_id}",
        "TRUNCATE score_ledger",
    ):
        nested = db_session.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            db_session.execute(text(statement))
        nested.rollback()
    assert _rows(db_session, sid)[0].score == 0.9


# ------------------------------------------------------------------ the score_history hook (Developer-1's cases)


def test_a_rerun_the_same_day_keeps_the_first_score_as_revision_one(db_session):
    inst = _instrument(db_session, "SH389B")
    _record(db_session, inst, 0.90, today=FRIDAY)
    _record(db_session, inst, 0.50, today=FRIDAY)
    sid = resolve(db_session, symbol="SH389B")
    assert [(r.revision, r.score) for r in _rows(db_session, sid)] == [(1, 0.90), (2, 0.50)]
    assert [r.score for r in ledger.history(db_session, sid, view="first")] == [0.90]


def test_the_old_table_keeps_its_one_row_a_day_behaviour(db_session):
    inst = _instrument(db_session, "SH389OLD")
    _record(db_session, inst, 0.90, today=FRIDAY)
    _record(db_session, inst, 0.50, today=FRIDAY)
    rows = list(db_session.scalars(select(StockScore).where(StockScore.instrument_id == inst.id)))
    assert [r.score for r in rows] == [0.50] and rows[0].as_of == FRIDAY


def test_a_rerun_with_the_same_value_adds_nothing_anywhere(db_session):
    inst = _instrument(db_session, "SH389C")
    for _ in range(2):
        _record(db_session, inst, 0.77, today=FRIDAY)
    assert len(_rows(db_session, resolve(db_session, symbol="SH389C"))) == 1


def test_a_run_after_midnight_is_dated_the_session_it_scored(db_session, monkeypatch):
    inst = _instrument(db_session, "SH389F")
    _candle(db_session, inst, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 21, 0, 30, tzinfo=IST))
    _record(db_session, inst, 0.81)
    old = db_session.scalar(select(StockScore.as_of).where(StockScore.instrument_id == inst.id))
    (row,) = _rows(db_session, resolve(db_session, symbol="SH389F"))
    assert old == FRIDAY and row.session_date == FRIDAY, "filed under the session, not the clock day"


def test_a_weekend_run_is_dated_the_last_session_not_the_weekend_day(db_session, monkeypatch):
    inst = _instrument(db_session, "SH389G")
    _candle(db_session, inst, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 22, 0, 30, tzinfo=IST))
    _record(db_session, inst, 0.81)
    (row,) = _rows(db_session, resolve(db_session, symbol="SH389G"))
    assert row.session_date == FRIDAY


def test_a_normal_scan_before_midnight_is_dated_that_session(db_session, monkeypatch):
    inst = _instrument(db_session, "SH389D")
    _candle(db_session, inst, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    _record(db_session, inst, 0.81)
    (row,) = _rows(db_session, resolve(db_session, symbol="SH389D"))
    assert row.session_date == FRIDAY


def test_no_candle_at_all_falls_back_to_the_clock_day_as_before(db_session, monkeypatch):
    inst = _instrument(db_session, "SH389NC")
    _at(monkeypatch, datetime(2026, 11, 23, 15, 50, tzinfo=IST))
    _record(db_session, inst, 0.81)
    (row,) = _rows(db_session, resolve(db_session, symbol="SH389NC"))
    assert row.session_date == date(2026, 11, 23)


def test_a_caller_that_passes_the_session_is_honoured(db_session, monkeypatch):
    inst = _instrument(db_session, "SH389H")
    _candle(db_session, inst, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 21, 0, 30, tzinfo=IST))
    _record(db_session, inst, 0.81, today=FRIDAY)
    assert _rows(db_session, resolve(db_session, symbol="SH389H"))[0].session_date == FRIDAY


def test_a_model_change_keeps_each_models_own_name_version_and_horizon(db_session):
    db_session.add_all(
        [
            MLModel(name="mdl389", version="v1", algorithm="x", prediction_horizon_days=5),
            MLModel(name="mdl389", version="v2", algorithm="x", prediction_horizon_days=15),
        ]
    )
    db_session.flush()
    inst = _instrument(db_session, "SWITCH389")
    _record(db_session, inst, 0.60, today=date(2026, 11, 19), model="mdl389:v1")
    _record(db_session, inst, 0.70, today=date(2026, 11, 20), model="mdl389:v2")
    rows = _rows(db_session, resolve(db_session, symbol="SWITCH389"))
    assert [(r.model_name, r.model_version, r.horizon_days, r.score) for r in rows] == [
        ("mdl389", "v1", 5, 0.60),
        ("mdl389", "v2", 15, 0.70),
    ]
    assert all(r.model_id is not None for r in rows)


def test_the_ledger_never_stops_a_scan(db_session, monkeypatch):
    inst = _instrument(db_session, "SAFE389")

    def boom(*args, **kwargs):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(ledger, "append_score", boom)
    assert _record(db_session, inst, 0.7, today=FRIDAY) == 1
    assert db_session.scalar(select(StockScore.score).where(StockScore.instrument_id == inst.id)) == 0.7


def test_a_stock_with_no_security_gets_one_when_it_is_first_scored(db_session):
    inst = _instrument(db_session, "AUTO389")
    assert resolve(db_session, symbol="AUTO389") is None
    _record(db_session, inst, 0.7, today=FRIDAY)
    assert resolve(db_session, symbol="AUTO389") is not None
