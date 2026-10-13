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


# --- the forward gate (protocol section 5a) ---------------------------------------------------------

from swing_trade_ml.brain.trial_journal import GATE_MIN_IDEAS, gate  # noqa: E402


def _summary(sessions, ideas, avg, edge):
    return {"sessions": sessions, "summaries": {"brain_trade": {"ideas": ideas, "avg_net": avg, "edge_vs_every_stock": edge}}}


def test_gate_is_too_early_below_either_minimum():
    assert gate(_summary(MIN_SESSIONS - 1, 50, 0.02, 0.01))["word"] == "too early"
    assert gate(_summary(MIN_SESSIONS, GATE_MIN_IDEAS - 1, 0.02, 0.01))["word"] == "too early"


def test_gate_passes_only_when_profitable_and_better_than_every_stock():
    assert gate(_summary(MIN_SESSIONS, GATE_MIN_IDEAS, 0.004, 0.002))["word"] == "pass"
    assert gate(_summary(MIN_SESSIONS, GATE_MIN_IDEAS, -0.001, 0.002))["word"] == "behind"
    assert gate(_summary(MIN_SESSIONS, GATE_MIN_IDEAS, 0.004, -0.001))["word"] == "behind"
    assert gate(_summary(MIN_SESSIONS, GATE_MIN_IDEAS, 0.004, None))["word"] == "behind"


def test_gate_flags_clearly_worse_than_every_stock():
    g = gate(_summary(MIN_SESSIONS, GATE_MIN_IDEAS, -0.02, -0.015))
    assert g["word"] == "behind" and g["clearly_worse"]
    assert not gate(_summary(MIN_SESSIONS, GATE_MIN_IDEAS, -0.001, -0.005))["clearly_worse"]


def test_report_opens_with_the_gate_answer():
    bars = {"UP": _bars(0.02)}
    j = build_journal([Session(DAY0, "NORMAL", (Idea("UP", "TRADE", 0.9),))], bars)
    assert "Gate answer: too early" in plain_report(j)


# --- F-13: NIFTY buy-and-hold and cash baselines -----------------------------------------------------


def test_nifty_held_fifteen_sessions_is_a_baseline():
    bars = {"UP": _bars(0.02)}
    sessions = [Session(DAY0, "NORMAL", (Idea("UP", "TRADE", 0.9),))]
    j = build_journal(sessions, bars, index_bars=_bars(0.01))
    n = j["summaries"]["nifty"]
    assert n["finished"] == 1 and n["open"] == 0
    # bought at the next open, sold at the 15th session's close: 15 days of +1% from that open
    assert abs(n["avg"] - (1.01**15 - 1)) < 1e-9


def test_nifty_without_fifteen_later_sessions_is_open_and_not_counted():
    sessions = [Session(_days(8)[3], "NORMAL", ())]
    j = build_journal(sessions, {}, index_bars=_bars(0.01, n=8))
    n = j["summaries"]["nifty"]
    assert n["finished"] == 0 and n["open"] == 1 and n["avg"] is None


def test_report_shows_nifty_and_cash_rows():
    bars = {"UP": _bars(0.02)}
    j = build_journal([Session(DAY0, "NORMAL", (Idea("UP", "TRADE", 0.9),))], bars, index_bars=_bars(0.01))
    text = plain_report(j)
    assert "NIFTY 50, held 15 sessions" in text and "| Cash |" in text


def test_no_index_data_means_no_nifty_row_but_cash_stays():
    j = build_journal([Session(DAY0, "NORMAL", ())], {})
    assert j["summaries"]["nifty"] is None
    assert "| Cash |" in plain_report(j)


# --- ideas the risk check blocked: shown, never counted ---------------------------------------------


def test_risk_blocked_ideas_are_their_own_set():
    s = Session(DAY0, "DEFENSIVE", (Idea("AAA", "WATCH", 0.7, blocked=True), Idea("BBB", "WATCH", 0.6)))
    p = picks_for(s)
    assert p["brain_blocked"] == ["AAA"] and p["brain_trade"] == []


def test_risk_blocked_ideas_never_count_toward_the_gate():
    bars = {"UP": _bars(0.02)}
    sessions = [Session(d, "DEFENSIVE", (Idea("UP", "WATCH", 0.9, blocked=True),)) for d in _days(MIN_SESSIONS)]
    j = build_journal(sessions, bars)
    assert j["summaries"]["brain_blocked"]["picked"] == MIN_SESSIONS
    assert j["summaries"]["brain_trade"]["ideas"] == 0
    assert gate(j)["word"] == "too early"
    assert "blocked by the risk check" in plain_report(j)
