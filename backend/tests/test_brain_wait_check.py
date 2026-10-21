"""ps11: was WAIT / AVOID the right call? Pure grouping and the fixed reading rule."""

from __future__ import annotations

from datetime import date

from swing_trade_ml.brain import wait_check as wc
from swing_trade_ml.brain.replay_scoring import StrictOutcome

D1, D2 = date(2026, 7, 13), date(2026, 7, 14)


def _o(status: str, ret: float | None) -> StrictOutcome:
    return StrictOutcome(status=status, net_return=ret, days=5, half_out=False, gap=False, exit_day=None)


def test_rows_are_grouped_by_the_brains_word_and_wanted_beats_the_word():
    rows = [
        wc.Judged(D1, "A", "WATCH", True),  # a lowered TRADE: wanted
        wc.Judged(D1, "B", "WAIT", False),
        wc.Judged(D1, "C", "AVOID", False),
        wc.Judged(D1, "D", "WATCH", False),  # a plain WATCH: only in "every stock-day"
    ]
    groups = {g: [r.symbol for r in rs] for g, rs in wc.grouped(rows).items()}
    assert groups == {"wanted": ["A"], "WAIT": ["B"], "AVOID": ["C"], "every stock-day": ["A", "B", "C", "D"]}


def test_summary_counts_exits_and_the_share_that_lost_money():
    rows = [wc.Judged(D1, s, "WAIT", False) for s in "ABCD"]
    outcomes = {
        (D1, "A"): _o("stop", -0.045),
        (D1, "B"): _o("target", 0.07),
        (D1, "C"): _o("timeout", -0.01),
        (D1, "D"): _o("open", None),  # not finished: left out
    }
    s = wc.summary(rows, outcomes)
    assert (s["stock_days"], s["finished"], s["stop"], s["target"], s["timeout"]) == (4, 3, 1, 1, 1)
    assert abs(s["lost_share"] - 2 / 3) < 1e-12
    assert abs(s["avg_net"] - (-0.045 + 0.07 - 0.01) / 3) < 1e-12


def test_days_where_wanted_beat_wait_need_both_groups_finished():
    rows = [
        wc.Judged(D1, "A", "WATCH", True),
        wc.Judged(D1, "B", "WAIT", False),
        wc.Judged(D2, "C", "WATCH", True),
        wc.Judged(D2, "D", "WAIT", False),
        wc.Judged(date(2026, 7, 15), "E", "WAIT", False),  # no wanted idea that day: not counted
    ]
    outcomes = {
        (D1, "A"): _o("target", 0.07),
        (D1, "B"): _o("stop", -0.045),
        (D2, "C"): _o("stop", -0.045),
        (D2, "D"): _o("timeout", 0.01),
        (date(2026, 7, 15), "E"): _o("stop", -0.045),
    }
    assert wc.day_by_day(rows, outcomes) == {"days": 2, "wanted_better": 1}


def test_reading_follows_the_fixed_rule():
    wait_lost = {"finished": 10, "avg_net": -0.004, "lost_share": 0.6}
    wanted_worse = {"finished": 5, "avg_net": -0.0099}
    text = wc.reading(wanted_worse, wait_lost)
    assert "right call on average" in text and "no better than" in text
    text = wc.reading({"finished": 5, "avg_net": 0.01}, {"finished": 10, "avg_net": 0.002, "lost_share": 0.4})
    assert "not the right call on average" in text and "did better than" in text
    empty = {"finished": 0, "avg_net": None}
    assert "nothing to judge" in wc.reading(empty, empty)


def test_input_file_round_trips(tmp_path):
    p = tmp_path / "j.json"
    p.write_text('{"fields":["day","symbol","word","liked"],"rows":[["2026-07-13","A","WAIT",false]]}')
    assert wc.load_judged(p) == [wc.Judged(D1, "A", "WAIT", False)]
