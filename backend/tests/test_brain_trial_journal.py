"""The trial journal: who each followed set picks, how ideas are scored, and what is called 'too early'."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from swing_trade_ml.brain.trial_journal import (
    MIN_SESSIONS,
    Idea,
    Session,
    build_journal,
    picks_for,
    plain_report,
)

DAY0 = date(2026, 1, 5)  # a Monday


def _days(n: int) -> list[date]:
    out, d = [], DAY0
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bars(daily_move: float, n: int = 40, start: float = 100.0) -> pd.DataFrame:
    rows, price = [], start
    for d in _days(n):
        nxt = price * (1 + daily_move)
        rows.append(
            {
                "day": d,
                "open": price,
                "high": max(price, nxt) * 1.001,
                "low": min(price, nxt) * 0.999,
                "close": nxt,
            }
        )
        price = nxt
    return pd.DataFrame(rows)


def test_each_set_takes_the_right_symbols():
    s = Session(
        DAY0,
        "NORMAL",
        (
            Idea("AAA", "TRADE", 0.91),
            Idea("BBB", "WATCH", 0.85),
            Idea("CCC", "WAIT", 0.40),
            Idea("DDD", "WAIT", None),  # no score: never ranked
            *(Idea(f"X{i}", "WAIT", 0.5 + i / 100) for i in range(6)),
        ),
    )
    p = picks_for(s, ["V1", "V1"])
    assert p["brain_trade"] == ["AAA"]
    assert p["brain_top5"][:2] == ["AAA", "BBB"] and len(p["brain_top5"]) == 5
    assert p["brain_over_80"] == ["AAA", "BBB"]
    assert p["v1_buys"] == ["V1"]


def test_owner_overrule_decides_the_word_not_the_score():
    s = Session(DAY0, "NORMAL", (Idea("AAA", "WATCH", 0.95),))  # overruled from TRADE to WATCH upstream
    assert picks_for(s)["brain_trade"] == []
    assert picks_for(s)["brain_over_80"] == ["AAA"]


def test_a_rising_stock_followed_beats_a_falling_one_and_costs_are_in():
    bars = {"UP": _bars(0.02), "DOWN": _bars(-0.02)}
    sessions = [Session(DAY0, "NORMAL", (Idea("UP", "TRADE", 0.9), Idea("DOWN", "WAIT", 0.2)))]
    j = build_journal(sessions, bars)
    trade = j["summaries"]["brain_trade"]
    assert trade["ideas"] == 1 and trade["hit_rate"] == 1.0
    assert 0 < trade["avg_net"] < 0.08  # target reached, less costs and slippage
    assert j["summaries"]["every_stock"]["ideas"] == 2
    assert j["summaries"]["brain_trade"]["edge_vs_every_stock"] > 0


def test_an_idea_without_enough_days_is_open_and_not_counted():
    bars = {"UP": _bars(0.001, n=8)}  # only a few bars after the decision day
    sessions = [Session(_days(8)[3], "NORMAL", (Idea("UP", "TRADE", 0.9),))]
    j = build_journal(sessions, bars)
    row = j["summaries"]["brain_trade"]
    assert row["picked"] == 1 and row["still_open"] == 1 and row["ideas"] == 0
    shown = j["days"][0]["picks"]["brain_trade"][0]
    assert shown["status"] == "open" and shown["so_far"] is not None


def test_fewer_than_the_minimum_sessions_is_called_too_early():
    bars = {"UP": _bars(0.02)}
    few = [Session(d, "NORMAL", (Idea("UP", "TRADE", 0.9),)) for d in _days(MIN_SESSIONS - 1)]
    enough = [Session(d, "NORMAL", (Idea("UP", "TRADE", 0.9),)) for d in _days(MIN_SESSIONS)]
    assert not build_journal(few, bars)["enough_sessions"]
    assert "Too early" in plain_report(build_journal(few, bars))
    assert build_journal(enough, bars)["enough_sessions"]
    assert "Too early" not in plain_report(build_journal(enough, bars))


def test_no_sessions_gives_a_plain_message_not_a_crash():
    j = build_journal([], {"UP": _bars(0.01)})
    assert j["sessions"] == 0
    assert "nothing to record" in plain_report(j)


def test_the_baseline_is_only_the_stocks_the_brain_looked_at_that_day():
    bars = {"UP": _bars(0.02), "DOWN": _bars(-0.02), "OTHER": _bars(0.02)}  # OTHER was never looked at
    sessions = [Session(DAY0, "NORMAL", (Idea("UP", "TRADE", 0.9), Idea("DOWN", "WAIT", 0.2)))]
    j = build_journal(sessions, bars)
    assert j["summaries"]["every_stock"]["ideas"] == 2
