# ruff: noqa: F811  (the shared `market` fixture is imported, then requested by name)
"""Horizon experiments: tests for the independent review's findings (17 Oct).

1. A rejected correction must not remove the original pick.
2. The protocol stored on first use is what the scorer uses, even if the app's cost settings change later.
3. A horizon whose exit falls in a year with no holiday list waits (pending) instead of refusing the pick.
4. Picks replaced by a correction do not linger in the report or the outcomes list.
5. The universe benchmark leaves out stocks with a big one-day jump or a split/bonus, like the picks.
6. The report counts independent samples as distinct entry dates, and says what it compares and leaves out.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from swing_trade_ml.db.models.experiments import ExperimentOutcome
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.services.experiments import ledger, report, rules, scorer
from swing_trade_ml.services.experiments.protocol import PROTOCOL_V1, Costs, ensure_owner_cohort
from test_experiments_ledger import SAT, _bars, _inst, ist, market  # noqa: F401  (market is a fixture)

IST = ZoneInfo("Asia/Kolkata")
END = ist(2026, 12, 31, 21)


def _outcome(db, sel, horizon):
    return db.scalar(
        select(ExperimentOutcome).where(
            ExperimentOutcome.selection_id == sel.id, ExperimentOutcome.horizon == horizon
        )
    )


def test_a_rejected_correction_keeps_the_original_pick(db_session, market):
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    bad = ledger.correct(
        db_session, sel.id, symbol="NOSUCHX", intended_horizon=5, note=None, user="owner", now=SAT
    )
    assert bad.status == "rejected"
    assert [s.id for s in ledger.active_selections(db_session)] == [sel.id]
    good = ledger.correct(
        db_session, sel.id, symbol="EXPC", intended_horizon=5, note=None, user="owner", now=SAT
    )
    assert good.status == "accepted"
    assert [s.id for s in ledger.active_selections(db_session)] == [good.id]


def test_the_scorer_uses_the_stored_protocol_not_todays_settings(db_session, market):
    ensure_owner_cohort(db_session)  # stores horizon-v1 with today's costs
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=END)
    before = _outcome(db_session, sel, 5).net_return
    changed = replace(PROTOCOL_V1, costs=Costs(500.0, 500.0, 500.0, 500.0))  # someone edits the app settings
    scorer.run(db_session, now=END, protocol=changed)
    assert _outcome(db_session, sel, 5).net_return == before


def test_a_missing_holiday_list_leaves_the_horizon_pending_not_refused(db_session, market, monkeypatch):
    real = rules.session_n

    def no_calendar_for_long_windows(entry, n):
        if n > 5:
            raise rules.CalendarMissingError("No NSE holiday list for 2099")
        return real(entry, n)

    monkeypatch.setattr(rules, "session_n", no_calendar_for_long_windows)
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    assert sel.status == "accepted"
    scorer.run(db_session, now=END)
    thirty = _outcome(db_session, sel, 30)
    assert thirty.state == "pending" and thirty.data_flags.get("holiday_calendar_missing")
    assert _outcome(db_session, sel, 5).state == "closed"


def test_replaced_picks_leave_the_report_and_the_outcomes(db_session, market, client):
    sel = ledger.submit(
        db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=ist(2026, 10, 16, 18)
    )
    scorer.run(db_session, now=ist(2026, 10, 16, 21))  # writes pending rows for EXPA
    ledger.correct(db_session, sel.id, symbol="EXPC", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=END)
    rep = report.build(db_session, today=date(2026, 12, 31))
    five = next(r for r in rep["horizons"] if r["horizon"] == 5)
    assert five["closed"] == 1 and five["pending"] == 0
    rows = client.get("/api/v1/experiments/outcomes", headers={"X-API-Key": "test-api-key"}).json()
    assert {r["symbol"] for r in rows} == {"EXPC"}


def test_the_universe_leaves_out_stocks_with_a_split_or_a_big_jump(db_session, market):
    split = _inst(db_session, "EXPSPLIT")
    _bars(db_session, split, date(2026, 10, 19), 40, open_=400.0, step=1.0, gap_on=date(2026, 10, 22))
    bonus = _inst(db_session, "EXPBONUS")
    _bars(db_session, bonus, date(2026, 10, 19), 40, open_=90.0, step=0.1)
    db_session.add(
        UpcomingEvent(
            symbol="EXPBONUS", kind="corporate_action", event_date=date(2026, 10, 21), detail="Bonus 1:1"
        )
    )
    db_session.flush()
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=END)
    o = _outcome(db_session, sel, 5)
    assert o.universe_count == 3  # EXPA, EXPB, EXPC; EXPSPLIT and EXPBONUS left out
    assert o.data_flags.get("universe_dropped") == 2


def test_the_report_counts_entry_dates_and_states_its_limits(db_session, market):
    ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    ledger.submit(
        db_session, symbol="EXPB", intended_horizon=5, note=None, user="owner", now=ist(2026, 10, 19, 10)
    )
    scorer.run(db_session, now=END)
    rep = report.build(db_session, today=date(2026, 12, 31))
    five = next(r for r in rep["horizons"] if r["horizon"] == 5)
    assert five["independent_samples"] == five["independent_entry_dates"] == 2
    assert "non_overlapping" in five
    text = " ".join(rep["limits"]).lower()
    assert "before costs" in text and "left out" in text and "same as" in text


def test_two_identical_picks_at_once_cannot_both_be_accepted(db_session, market):
    # The duplicate rule holds under a per-stock lock; within one transaction the second sees the first.
    a = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    b = ledger.submit(db_session, symbol="EXPA", intended_horizon=5, note=None, user="owner", now=SAT)
    assert (a.status, b.status) == ("accepted", "rejected")
    with open(ledger.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "pg_advisory_xact_lock" in src


def test_scoring_a_holiday_index_bar_never_marks_on_a_non_session(db_session, market):
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.market import Candle, Instrument

    nifty = db_session.scalar(
        select(Instrument).where(Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL)
    )
    holiday = date(2026, 11, 10)  # Diwali Balipratipada: a Muhurat-style bar on a holiday
    db_session.add(
        Candle(
            instrument_id=nifty.id,
            interval="day",
            ts=datetime(2026, 11, 10, tzinfo=IST),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1,
        )
    )
    db_session.flush()
    sel = ledger.submit(db_session, symbol="EXPA", intended_horizon=30, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=ist(2026, 11, 10, 21))
    o = _outcome(db_session, sel, 30)
    assert o.state == "open" and o.mark_session != holiday
