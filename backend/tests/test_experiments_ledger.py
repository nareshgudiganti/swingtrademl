"""Horizon experiments (design rev 3): the append-only pick record, the scorer and the report (test database).

Every test passes `now` explicitly, so nothing depends on the real clock."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.experiments import ExperimentJobRun, ExperimentOutcome, ExperimentSelection
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.services.experiments import ledger, report, rules, scorer
from swing_trade_ml.services.experiments.protocol import PROTOCOL_V1

IST = ZoneInfo("Asia/Kolkata")
_token = iter(range(9_100_000, 9_200_000))


def ist(y, m, d, hh=7, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def _inst(db, sym, *, segment="NSE", itype="EQ"):
    inst = Instrument(
        instrument_token=next(_token),
        tradingsymbol=sym,
        exchange="NSE",
        segment=segment,
        instrument_type=itype,
    )
    db.add(inst)
    db.flush()
    return inst


def _bars(db, inst, start: date, n_sessions: int, *, open_=100.0, step=1.0, gap_on: date | None = None):
    """Daily bars on n trading sessions from `start`: close rises by `step` a day; open = previous close."""
    d, close, out = start, open_, []
    for _ in range(n_sessions):
        while not rules.is_trading_day(d):
            d += timedelta(days=1)
        o = close
        close = o + step
        if gap_on is not None and d == gap_on:
            close = o * 0.5  # a 50% one-day drop: an unadjusted split
        db.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=datetime(d.year, d.month, d.day, tzinfo=IST),
                open=o,
                high=max(o, close),
                low=min(o, close),
                close=close,
                volume=1000,
            )
        )
        out.append((d, o, close))
        d += timedelta(days=1)
    db.flush()
    return out


@pytest.fixture()
def market(db_session):
    """NIFTY and three stocks with 40 sessions of prices from Mon 19 Oct 2026."""
    start = date(2026, 10, 19)
    nifty = _inst(db_session, settings.BENCHMARK_INDEX_SYMBOL, segment="INDICES", itype=None)
    _bars(db_session, nifty, start, 40, open_=24_000.0, step=10.0)
    bank = _inst(
        db_session, "NIFTY BANK", segment="INDICES", itype=None
    )  # another index: never in the universe
    _bars(db_session, bank, start, 40, open_=50_000.0, step=500.0)
    stocks = {s: _inst(db_session, s) for s in ("EXPA", "EXPB", "EXPC")}
    _bars(db_session, stocks["EXPA"], start, 40, open_=100.0, step=1.0)
    _bars(db_session, stocks["EXPB"], start, 40, open_=200.0, step=-1.0)
    _bars(db_session, stocks["EXPC"], start, 40, open_=50.0, step=0.5)
    _inst(db_session, "EXPNOPRICE")  # listed, never traded
    return stocks


SAT = ist(2026, 10, 17, 11)  # a Saturday: picks enter Monday 19 Oct


# ------------------------------------------------------------------- record --


def test_a_pick_is_recorded_with_its_entry_session(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note="breakout", user="owner", now=SAT)
    assert sel.status == "accepted"
    assert sel.entry_session == date(2026, 10, 19)
    assert sel.symbol_at_entry == "EXPA" and sel.instrument_id == market["EXPA"].id
    assert sel.intended_horizon == 5 and sel.submitted_by == "owner"


def test_an_unknown_or_unpriced_stock_is_rejected_and_kept(db_session, market):
    for sym in ("NOSUCH", "EXPNOPRICE"):
        sel = ledger.submit(db_session, symbol=sym, intended_horizon=30, note=None, user="owner", now=SAT)
        assert sel.status == "rejected" and sel.reject_reason
    assert db_session.scalar(select(func.count()).select_from(ExperimentSelection)) == 2


def test_the_index_itself_is_not_a_stock_pick(db_session, market):
    sel = ledger.submit(
        db_session,
        symbol=settings.BENCHMARK_INDEX_SYMBOL,
        intended_horizon=5,
        note=None,
        user="owner",
        now=SAT,
    )
    assert sel.status == "rejected"


def test_a_duplicate_within_30_sessions_is_rejected_with_a_reason(db_session, market):
    ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    again = ledger.submit(
        db_session, symbol="expa", intended_horizon=30, note=None, user="owner", now=ist(2026, 10, 26, 7)
    )
    assert again.status == "rejected" and "already" in again.reject_reason.lower()


def test_the_same_stock_is_allowed_again_after_its_30_session_window(db_session, market):
    first = ledger.submit(db_session, symbol="EXPA", intended_horizon=30, note=None, user="owner", now=SAT)
    after = rules.session_n(first.entry_session, 30)
    later = ledger.submit(
        db_session,
        symbol="EXPA",
        intended_horizon=30,
        note=None,
        user="owner",
        now=datetime(after.year, after.month, after.day, 18, tzinfo=IST),
    )
    assert later.status == "accepted"


def test_a_correction_before_the_cutoff_supersedes_the_original(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    fix = ledger.correct(
        db_session,
        sel.id,
        symbol="EXPC",
        intended_horizon=30,
        note="typo",
        user="owner",
        now=ist(2026, 10, 19, 8, 30),
    )
    assert fix.supersedes_id == sel.id and fix.status == "accepted" and fix.symbol_at_entry == "EXPC"
    assert fix.entry_session == sel.entry_session
    assert ledger.active_selections(db_session) == [fix]


def test_a_correction_after_the_cutoff_is_refused(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    with pytest.raises(ledger.TooLateError):
        ledger.correct(
            db_session,
            sel.id,
            symbol="EXPC",
            intended_horizon=5,
            note=None,
            user="owner",
            now=ist(2026, 10, 19, 9, 0),
        )


def test_the_database_refuses_to_edit_or_delete_a_pick(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    db_session.flush()
    for sql in (
        "UPDATE experiment_selections SET note = 'x' WHERE id = :i",
        "DELETE FROM experiment_selections WHERE id = :i",
    ):
        sp = db_session.begin_nested()
        with pytest.raises(DBAPIError):
            db_session.execute(text(sql), {"i": sel.id})
            db_session.flush()
        sp.rollback()


# ------------------------------------------------------------------- scorer --


def _outcome(db, sel, horizon):
    return db.scalar(
        select(ExperimentOutcome).where(
            ExperimentOutcome.selection_id == sel.id, ExperimentOutcome.horizon == horizon
        )
    )


def test_scoring_closes_both_horizons_with_net_returns_and_benchmarks(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    for h in (5, 30):
        o = _outcome(db_session, sel, h)
        assert o.state == "closed", (h, o.state, o.data_flags)
        assert o.exit_session == rules.session_n(sel.entry_session, h)
        entry = db_session.scalar(
            select(Candle.open).where(
                Candle.instrument_id == market["EXPA"].id, Candle.ts == datetime(2026, 10, 19, tzinfo=IST)
            )
        )
        assert o.entry_price == pytest.approx(entry)
        assert o.gross_return == pytest.approx(o.exit_price / o.entry_price - 1)
        assert o.net_return < o.gross_return
        assert o.buy_hold_return == pytest.approx(o.gross_return)
        assert o.nifty_return is not None and o.universe_return is not None
        assert o.excess_vs_nifty == pytest.approx(o.net_return - o.nifty_return)


def test_the_universe_benchmark_excludes_indices_and_uses_the_same_sessions(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    o = _outcome(db_session, sel, 5)
    exit_day = o.exit_session
    rets = []
    for s in ("EXPA", "EXPB", "EXPC"):
        iid = market[s].id
        op = db_session.scalar(
            select(Candle.open).where(
                Candle.instrument_id == iid, Candle.ts == datetime(2026, 10, 19, tzinfo=IST)
            )
        )
        cl = db_session.scalar(
            select(Candle.close).where(
                Candle.instrument_id == iid,
                Candle.ts == datetime(exit_day.year, exit_day.month, exit_day.day, tzinfo=IST),
            )
        )
        rets.append(cl / op - 1)
    assert o.universe_return == pytest.approx(sum(rets) / len(rets))


def test_a_pick_still_running_is_open_and_marked_to_market(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=30, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 10, 23, 21))
    o = _outcome(db_session, sel, 30)
    assert o.state == "open" and o.exit_session is None and o.gross_return is not None


def test_a_pick_not_yet_entered_is_pending(db_session, market):
    sel = ledger.submit(
        db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=ist(2026, 12, 4, 10)
    )
    scorer.run(db_session, now=ist(2026, 12, 4, 21))
    assert _outcome(db_session, sel, 5).state == "pending"


def test_a_big_one_day_gap_is_a_data_issue_not_a_score(db_session, market):
    gappy = _inst(db_session, "EXPGAP")
    _bars(db_session, gappy, date(2026, 10, 19), 40, open_=300.0, step=1.0, gap_on=date(2026, 10, 22))
    sel = ledger.submit(db_session, symbol="EXPGAP", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    o = _outcome(db_session, sel, 5)
    assert o.state == "data_issue" and o.data_flags.get("big_gap") and o.net_return is None


def test_a_corporate_action_in_the_window_is_a_data_issue(db_session, market):
    db_session.add(
        UpcomingEvent(
            symbol="EXPC", kind="corporate_action", event_date=date(2026, 10, 22), detail="Bonus 1:1"
        )
    )
    db_session.flush()
    sel = ledger.submit(db_session, symbol="EXPC", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    o = _outcome(db_session, sel, 5)
    assert o.state == "data_issue" and o.data_flags.get("corporate_action")


def test_a_missing_bar_when_the_market_traded_is_a_data_issue(db_session, market):
    holey = _inst(db_session, "EXPHOLE")
    _bars(db_session, holey, date(2026, 10, 19), 40, open_=80.0, step=0.2)
    exit5 = rules.session_n(date(2026, 10, 19), 5)
    db_session.execute(
        text("DELETE FROM candles WHERE instrument_id = :i AND ts = :t"),
        {"i": holey.id, "t": datetime(exit5.year, exit5.month, exit5.day, tzinfo=IST)},
    )
    sel = ledger.submit(db_session, symbol="EXPHOLE", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    o = _outcome(db_session, sel, 5)
    assert o.state == "data_issue" and o.data_flags.get("missing_bar")


def test_scoring_twice_gives_the_same_rows(db_session, market):
    ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    ledger.submit(db_session, symbol="EXPB", intended_horizon=30, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    first = [
        (o.selection_id, o.horizon, o.state, o.net_return)
        for o in db_session.scalars(select(ExperimentOutcome).order_by(ExperimentOutcome.id))
    ]
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    second = [
        (o.selection_id, o.horizon, o.state, o.net_return)
        for o in db_session.scalars(select(ExperimentOutcome).order_by(ExperimentOutcome.id))
    ]
    assert first == second and len(first) == 4


def test_superseded_and_rejected_picks_are_never_scored(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    ledger.correct(db_session, sel.id, symbol="EXPB", intended_horizon=5, note=None, user="owner", now=SAT)
    ledger.submit(db_session, symbol="NOSUCH", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    scored = {o.selection_id for o in db_session.scalars(select(ExperimentOutcome))}
    assert sel.id not in scored and len(scored) == 1


def test_every_run_is_recorded(db_session, market):
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    runs = list(db_session.scalars(select(ExperimentJobRun)))
    assert runs and runs[-1].status == "done" and runs[-1].finished_at is not None


def test_a_second_scorer_running_at_the_same_time_steps_aside(db_session, market, db_engine):
    other = db_engine.connect()
    try:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": scorer.LOCK_KEY})
        result = scorer.run(db_session, now=ist(2026, 12, 31, 21))
        assert result.status == "skipped_locked"
    finally:
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": scorer.LOCK_KEY})
        other.close()


# ------------------------------------------------------------------- report --


def test_the_report_states_sample_size_uncertainty_and_never_validates(db_session, market):
    ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    ledger.submit(db_session, symbol="EXPB", intended_horizon=30, note=None, user="owner", now=SAT)
    ledger.submit(db_session, symbol="EXPC", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    rep = report.build(db_session, today=date(2026, 12, 31))
    by_h = {r["horizon"]: r for r in rep["horizons"]}
    assert set(by_h) == {5, 30}
    five = by_h[5]
    assert five["closed"] == 3 and five["independent_entry_dates"] == 1 and five["non_overlapping"] == 1
    assert five["label"] == "Research, owner-selected, unproven"
    assert five["verdict"] == "Not proven"
    assert {
        "mean_net_return",
        "median_net_return",
        "mean_net_return_per_day",
        "mean_excess_vs_nifty",
        "mean_excess_vs_universe",
        "net_return_range_90",
        "win_rate",
        "period",
        "data_issues",
    } <= set(five)
    assert "validated" not in str(rep).lower()
    assert rep["protocol"]["code"] == PROTOCOL_V1.code
    assert rep["owner_selected_note"]


def test_the_report_by_intended_horizon(db_session, market):
    ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    ledger.submit(db_session, symbol="EXPB", intended_horizon=30, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 12, 31, 21))
    rep = report.build(db_session, today=date(2026, 12, 31), intended=5)
    assert {r["horizon"]: r["closed"] for r in rep["horizons"]} == {5: 1, 30: 1}
