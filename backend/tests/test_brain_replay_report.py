# backend/tests/test_brain_replay_report.py
from __future__ import annotations

from datetime import date

from swing_trade_ml.brain.modules.m09_learn.outcomes import Outcome
from swing_trade_ml.brain.replay_report import (
    BREAK_EVEN,
    LIMITATIONS,
    ScoredIdea,
    all_eligible_stats,
    plain_summary,
    random_baseline,
    track_stats,
)
from swing_trade_ml.brain.replay_scoring import StrictOutcome

D = date(2026, 9, 1)


def strict(status, ret=None, half=False, gap=False):
    return StrictOutcome(status, ret, 5 if ret is not None else None, half, gap, D)


def idea(symbol, status, ret=None, score=70, track_b=True, locked=None, no_data=False):
    return ScoredIdea(
        day=D,
        symbol=symbol,
        word="TRADE" if track_b else "WATCH",
        track_b=track_b,
        blocked=not track_b,
        score=score,
        reasons=("because",),
        locked=locked,
        strict=None if no_data else strict(status, ret),
    )


def test_break_even_is_one_third_before_costs():
    assert round(BREAK_EVEN, 3) == 0.333


def test_stats_on_no_ideas_do_not_divide_by_zero():
    s = track_stats([])
    assert s["ideas"] == 0 and s["resolved"] == 0 and s["hit_rate"] is None and s["avg_net_return"] is None


def test_open_and_no_price_data_are_never_counted_as_wins_or_losses():
    s = track_stats([idea("A", "open"), idea("B", "open", no_data=True), idea("C", "target", 0.07)])
    assert (s["ideas"], s["open"], s["no_price_data"], s["resolved"]) == (3, 1, 1, 1)
    assert s["target"] == 1 and s["hit_rate"] == 1.0


def test_hit_rate_and_average_net_return():
    s = track_stats([idea("A", "target", 0.07), idea("B", "stop", -0.045), idea("C", "timeout", 0.01)])
    assert s["resolved"] == 3 and round(s["hit_rate"], 3) == 0.333
    assert round(s["avg_net_return"], 4) == round((0.07 - 0.045 + 0.01) / 3, 4)


def test_locked_return_averages_only_where_it_exists():
    lk = Outcome("target", 0.08, 3, 0.09, -0.01, D)
    s = track_stats([idea("A", "target", 0.07, locked=lk), idea("B", "stop", -0.04)])
    assert s["avg_locked_return"] == 0.08


def test_score_buckets_split_hit_rates():
    s = track_stats(
        [
            idea("A", "target", 0.07, score=85),
            idea("B", "stop", -0.04, score=85),
            idea("C", "stop", -0.04, score=62),
        ]
    )
    assert s["by_score"]["80+"] == {"resolved": 2, "hit_rate": 0.5}
    assert s["by_score"]["60-69"] == {"resolved": 1, "hit_rate": 0.0}


def test_random_baseline_is_repeatable_and_ordered():
    pool = {D: ["A", "B", "C", "D"]}
    outcomes = {
        ("A", D): strict("target", 0.07),
        ("B", D): strict("stop", -0.045),
        ("C", D): strict("stop", -0.045),
        ("D", D): strict("open"),
    }
    one = random_baseline(pool, {D: 2}, outcomes, draws=50, seed=1)
    two = random_baseline(pool, {D: 2}, outcomes, draws=50, seed=1)
    assert one == two
    assert one["p5"] <= one["mean"] <= one["p95"]


def test_random_baseline_with_no_picks_is_empty_not_an_error():
    out = random_baseline({D: ["A"]}, {}, {}, draws=10, seed=1)
    assert out["mean"] is None


def test_all_eligible_counts_every_stock_that_day():
    pool = {D: ["A", "B"]}
    outcomes = {("A", D): strict("target", 0.07), ("B", D): strict("stop", -0.045)}
    s = all_eligible_stats(pool, outcomes)
    assert s["ideas"] == 2 and s["resolved"] == 2 and s["hit_rate"] == 0.5


def test_summary_says_plainly_when_nothing_is_resolved():
    report = {
        "window": {"from": "2026-09-01", "to": "2026-09-05", "days_replayed": 5, "failed_days": []},
        "track_a": track_stats([idea("A", "open")]),
        "track_b": track_stats([]),
        "baselines": {},
        "limitations": list(LIMITATIONS),
    }
    text = plain_summary(report)
    assert "not enough finished ideas" in text.lower()
    assert "5" in text


def test_summary_lists_failed_days_and_limitations():
    report = {
        "window": {
            "from": "2026-09-01",
            "to": "2026-09-05",
            "days_replayed": 4,
            "failed_days": ["2026-09-03"],
        },
        "track_a": track_stats([idea("A", "target", 0.07)]),
        "track_b": track_stats([idea("A", "target", 0.07)]),
        "baselines": {
            "random": {"mean": 0.0, "p5": -0.01, "p95": 0.01, "draws": 50},
            "all_eligible": track_stats([]),
        },
        "limitations": list(LIMITATIONS),
    }
    text = plain_summary(report)
    assert "2026-09-03" in text and "limits" in text.lower()
