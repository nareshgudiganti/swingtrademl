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
