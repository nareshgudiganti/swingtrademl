"""evidence-defs-v1 trade-level baselines (evidence plan A4, section 3a locked as tag evidence-defs-v1).

Brought across from feature/evidence-phase-a (3686a1c), trade level only: the portfolio-level accounts are
outside the approved Phase 1A scope."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from swing_trade_ml.brain.replay_scoring import StrictOutcome
from swing_trade_ml.services.brain_observatory import baselines, defs

START = date(2026, 1, 1)


def _days(n: int) -> list[date]:
    out, d = [], START
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = _days(70)
DECIDE = DAYS[30]  # 30 bars of history before it, so the 20-day momentum exists


def _bars(step: float) -> pd.DataFrame:
    """Each day opens at the previous close and closes `step` higher (or lower)."""
    rows, price = [], 100.0
    for d in DAYS:
        close = price * (1 + step)
        hi, lo = max(price, close), min(price, close)
        rows.append({"day": d, "open": price, "high": hi * 1.001, "low": lo * 0.999, "close": close})
        price = close
    return pd.DataFrame(rows)


def _flat() -> pd.DataFrame:
    return pd.DataFrame([{"day": d, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0} for d in DAYS])


BARS = {
    "UP1": _bars(0.02),
    "UP2": _bars(0.015),
    "FL1": _flat(),
    "FL2": _flat(),
    "FL3": _flat(),
    "DN1": _bars(-0.02),
    "DN2": _bars(-0.015),
}
POOL = {DECIDE: sorted(BARS)}
INDEX = _flat()


def test_summarise_counts_finished_open_and_missing():
    outs = [
        StrictOutcome("target", 0.07, 4, True, False, DAYS[1]),
        StrictOutcome("stop", -0.04, 2, False, False, DAYS[1]),
        StrictOutcome("open", None, None, False, False, None),
        None,
    ]
    s = baselines.summarise(outs)
    assert (s["picked"], s["finished"], s["open"], s["no_data"]) == (4, 2, 1, 1)
    assert s["avg_net"] == pytest.approx(0.015)
    assert s["hit_rate"] == 0.5


def test_trade_level_known_answers():
    t = baselines.trade_level({DECIDE: ["UP1"]}, POOL, BARS, INDEX, draws=200)
    assert t["defs"] == defs.EVIDENCE_DEFS_VERSION
    cand, every = t["candidate"], t["every_stock"]
    assert cand["finished"] == 1 and cand["hit_rate"] == 1.0  # a steady +2% a day reaches +8%
    assert every["finished"] == 7  # the whole pool on the candidate's one day
    assert cand["avg_net"] > every["avg_net"]
    # momentum 5 = the five strongest 20-day risers: both risers and the three flat stocks, no fallers
    assert t["momentum_5"]["picked"] == 5
    assert t["momentum_5"]["avg_net"] > every["avg_net"]
    # random 5 never beats a candidate that took the best stock; every draw is from the same pool
    assert t["random_5"]["draws"] == 200 and t["random_5"]["beaten_share"] == 1.0
    assert t["cash"]["avg_net"] == 0.0
    # flat NIFTY over the idea's own holding days loses exactly the round-trip costs
    assert t["nifty_matched"]["finished"] == 1
    assert -0.01 < t["nifty_matched"]["avg_net"] < 0
    assert "not an index strategy" in t["nifty_matched"]["note"]
    assert t["edge"]["word"] == "insufficient"  # one day is far below the 30-day minimum
    assert t["coverage"] == {"days_with_ideas": 1, "days_available": 1}


def test_trade_level_uses_only_the_candidates_days():
    other = DAYS[35]
    pool = {DECIDE: sorted(BARS), other: sorted(BARS)}
    t = baselines.trade_level({DECIDE: ["UP1"], other: []}, pool, BARS, INDEX, draws=10)
    assert t["every_stock"]["picked"] == 7  # not 14: the empty day is not a candidate day
    assert t["coverage"] == {"days_with_ideas": 1, "days_available": 2}


def test_random_5_is_seeded_and_equals_every_stock_when_the_pool_is_five():
    pool = {DECIDE: ["UP1", "FL1", "FL2", "DN1", "DN2"]}
    a = baselines.trade_level({DECIDE: ["UP1"]}, pool, BARS, INDEX, draws=50)
    b = baselines.trade_level({DECIDE: ["UP1"]}, pool, BARS, INDEX, draws=50)
    assert a["random_5"] == b["random_5"]
    assert a["random_5"]["avg_net_mean"] == pytest.approx(a["every_stock"]["avg_net"])


def test_index_matched_return_charges_costs_and_ends_on_the_exit_day():
    flat = baselines.index_matched_return(INDEX, DECIDE, DAYS[40])
    rising = baselines.index_matched_return(_bars(0.01), DECIDE, DAYS[33])
    assert -0.01 < flat < 0
    # 3 bars held: the open after DECIDE to the close of DAYS[33], minus costs
    assert rising == pytest.approx(1.01**3 - 1, abs=0.004)
    assert baselines.index_matched_return(INDEX, DAYS[-1], DAYS[-1]) is None


# --- the code's definitions are the frozen plan's ------------------------------------------------


def _plan_text() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / defs.PLAN_FILE).read_text(encoding="utf-8")


def test_definitions_match_the_frozen_plan():
    text = _plan_text()
    assert "FROZEN" in text and defs.EVIDENCE_DEFS_VERSION in text
    assert f"{defs.TRADE_RANDOM_DRAWS:,} seeded draws of {defs.TOP_N} random stocks" in text
    assert f"{defs.PORTFOLIO_RANDOM_RUNS} seeded runs" in text
    assert f"{defs.MOMENTUM_BARS}-day return" in text
    assert re.search(
        rf"runs of\s+{defs.BLOCK_DAYS} consecutive trading days, "
        rf"{defs.BOOTSTRAP_DRAWS:,} draws, seed {defs.BOOTSTRAP_SEED}",
        text,
    )
    assert f"Fewer than {defs.MIN_CONFIDENCE_DAYS} trading days with ideas" in text
    minus = "\N{MINUS SIGN}"
    assert f"over +{defs.RISING_OVER:.0%} = rising, under {minus}{-defs.FALLING_UNDER:.0%}" in text
    assert f"{defs.MAX_DRAWDOWN_HALT:.0%} drawdown halt" in text


def test_definitions_reuse_the_settled_rule_and_tools():
    from swing_trade_ml.brain import replay_scoring, walk_forward

    assert (
        replay_scoring.TARGET,
        replay_scoring.STOP,
        replay_scoring.HALF_OUT,
        replay_scoring.HORIZON_BARS,
    ) == (
        0.08,
        0.04,
        0.05,
        15,
    )
    assert walk_forward.MOMENTUM_BARS == defs.MOMENTUM_BARS
    assert walk_forward.BLOCK_DAYS == defs.BLOCK_DAYS
    assert (walk_forward.RISING_OVER, walk_forward.FALLING_UNDER) == (defs.RISING_OVER, defs.FALLING_UNDER)
