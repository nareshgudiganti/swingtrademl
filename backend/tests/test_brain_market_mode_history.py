"""The recorded market mode per day, read back from the brain runs, and how replays report coverage."""

from __future__ import annotations

from datetime import timedelta

from brain_m18_fixtures import DAY, run
from swing_trade_ml.brain import portfolio_sim
from swing_trade_ml.brain.market_mode_history import coverage, mode_history
from swing_trade_ml.services import brain_weekly_health as w


def _mode(db, run_id, mode, day=DAY, **kw):
    r = run(db, run_id, day, **kw)
    r.banner_mode = mode
    db.flush()
    return r


def test_one_mode_per_day_from_the_newest_finished_nightly(db_session):
    _mode(db_session, "mh-1", "NORMAL", hh=15, mm=40)
    _mode(db_session, "mh-2", "DEFENSIVE", hh=15, mm=55)
    _mode(db_session, "mh-3", "NO_NEW_TRADES", kind="intraday", hh=16)  # intraday never counts
    _mode(db_session, "mh-4", "NORMAL", day=DAY + timedelta(days=1), status="failed")
    _mode(db_session, "mh-5", None, day=DAY + timedelta(days=2))  # no banner stored
    _mode(db_session, "mh-6", "SOMETHING_ELSE", day=DAY + timedelta(days=3))
    history = mode_history(db_session)
    assert history[DAY] == "DEFENSIVE"
    assert not any(d in history for d in (DAY + timedelta(days=n) for n in (1, 2, 3)))


def test_coverage_counts_only_recorded_days():
    modes = {DAY: "NORMAL"}
    assert coverage(modes, [DAY, DAY + timedelta(days=1)]) == (1, 2)
    assert coverage({}, []) == (0, 0)


def test_replay_limits_state_how_many_days_had_a_recorded_mode():
    none = portfolio_sim.limits_for_coverage(0, 40)
    assert any("every day is NORMAL" in t for t in none)
    some = portfolio_sim.limits_for_coverage(12, 40)
    assert any("12 of the 40 scored days" in t and "treated as NORMAL" in t for t in some)
    full = portfolio_sim.limits_for_coverage(40, 40)
    assert any("40 of the 40" in t and "Every day had a recorded mode" in t for t in full)
    assert not any("every day is NORMAL" in t for t in full)


def test_weekly_health_reports_banner_history(db_session):
    _mode(db_session, "mh-7", "DEFENSIVE")
    check = w.check_banner_history(db_session, DAY, days=5)
    assert check["ok"] and check["level"] == "info"
    assert "1 of the last 5 trading days" in check["detail"]


# --- tv6: one mode per past trading day, recorded first, otherwise derived point-in-time ---------------

import pandas as pd  # noqa: E402

from brain_m18_fixtures import candle, instrument  # noqa: E402
from swing_trade_ml.brain import market_mode_history as mmh  # noqa: E402
from swing_trade_ml.brain.reader import DatedReader  # noqa: E402


def test_history_prefers_the_recorded_banner_and_derives_only_the_gaps(db_session, monkeypatch):
    _mode(db_session, "mh-8", "DEFENSIVE")
    asked: list = []

    def fake_derive(db, day):
        asked.append(day)
        return "NORMAL"

    monkeypatch.setattr(mmh, "derived_mode", fake_derive)
    later = DAY + timedelta(days=1)
    history = mmh.history_for(db_session, [DAY, later])
    assert history[DAY] == ("DEFENSIVE", "recorded")
    assert history[later] == ("NORMAL", "derived")
    assert asked == [later]  # a recorded day is never re-derived
    assert mmh.modes_only(history) == {DAY: "DEFENSIVE", later: "NORMAL"}
    assert mmh.source_counts(history, [DAY, later, DAY + timedelta(days=2)]) == {
        "recorded": 1,
        "derived": 1,
        "missing": 1,
    }


def test_history_without_deriving_leaves_the_gaps_missing(db_session, monkeypatch):
    monkeypatch.setattr(mmh, "derived_mode", lambda db, day: (_ for _ in ()).throw(AssertionError("derived")))
    assert mmh.history_for(db_session, [DAY], derive=False) == {}


def test_a_day_that_cannot_be_derived_is_missing_not_guessed(db_session, monkeypatch):
    monkeypatch.setattr(mmh, "derived_mode", lambda db, day: None)
    assert mmh.history_for(db_session, [DAY]) == {}


def test_derived_mode_reads_only_data_up_to_that_day(db_session, monkeypatch):
    """A crash on the next day must not change the mode derived for this day (no look-ahead)."""
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "BENCHMARK_INDEX_SYMBOL", "TV6NIFTY")
    monkeypatch.setattr(DatedReader, "vix_closes", lambda self: pd.Series(dtype=float))
    monkeypatch.setattr(DatedReader, "breadth_series", lambda self: pd.Series(dtype=float))
    inst = instrument(db_session, "TV6NIFTY", 918601)
    first = DAY - timedelta(days=300)
    for n in range(301):
        candle(db_session, inst, first + timedelta(days=n), 100.0 + n * 0.1)
    crash_day = DAY + timedelta(days=1)
    candle(db_session, inst, crash_day, (100.0 + 300 * 0.1) * 0.95)
    assert mmh.derived_mode(db_session, DAY) != "NO_NEW_TRADES"
    assert mmh.derived_mode(db_session, crash_day) == "NO_NEW_TRADES"


def test_derived_mode_uses_a_replay_reader_at_the_end_of_the_ist_day(db_session, monkeypatch):
    seen = []

    def capture(reader):
        seen.append(reader)
        raise RuntimeError("stop here")

    monkeypatch.setattr(mmh, "inputs_from", capture)
    assert mmh.derived_mode(db_session, DAY) is None  # an error is "unknown", never a guess
    (reader,) = seen
    assert reader.live is False
    assert reader.as_of.astimezone(mmh.IST).date() == DAY
    assert (reader.as_of.astimezone(mmh.IST).hour, reader.as_of.astimezone(mmh.IST).minute) == (23, 59)


def test_history_command_prints_one_line_per_trading_day(db_session, monkeypatch, capsys):
    from contextlib import contextmanager

    _mode(db_session, "mh-9", "NO_NEW_TRADES")

    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(mmh, "_session", scope)
    monkeypatch.setattr(mmh, "derived_mode", lambda db, day: "DEFENSIVE")
    assert mmh.main(["--from", DAY.isoformat(), "--to", (DAY + timedelta(days=1)).isoformat()]) == 0
    out = capsys.readouterr().out
    assert f"{DAY.isoformat()}  NO_NEW_TRADES  recorded" in out
    assert f"{(DAY + timedelta(days=1)).isoformat()}  DEFENSIVE  derived" in out
    assert "1 recorded, 1 derived, 0 missing" in out
