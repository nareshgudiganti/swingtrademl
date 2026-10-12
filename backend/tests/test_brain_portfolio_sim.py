# backend/tests/test_brain_portfolio_sim.py
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from swing_trade_ml.brain.portfolio_sim import Pick, random_baseline, simulate

START = date(2026, 1, 5)
DAYS = [START + timedelta(days=i) for i in range(30)]  # day numbers only; weekends do not matter here


def flat(price=100.0, n=30, overrides=None):
    rows = []
    for i in range(n):
        o = h = lo = c = price
        if overrides and i in overrides:
            o, h, lo, c = overrides[i]
        rows.append({"day": DAYS[i], "open": o, "high": h, "low": lo, "close": c})
    return pd.DataFrame(rows)


def run(picks, bars, capital=500_000, modes=None):
    return simulate(picks, bars, DAYS, capital=capital, modes=modes)


def test_a_flat_stock_only_costs_money():
    r = run([Pick(DAYS[0], "A", 0.9)], {"A": flat()})
    assert r.trades == 1 and r.still_open == 0
    assert -0.01 < r.total_return < 0  # costs and slippage only, on one position
    assert r.avg_trade_return < 0


def test_a_target_hit_makes_money_and_a_stop_loses():
    up = flat(overrides={3: (100, 109, 100, 108)})
    down = flat(overrides={3: (100, 100, 94, 95)})
    assert run([Pick(DAYS[0], "A", 0.9)], {"A": up}).total_return > 0.005
    lost = run([Pick(DAYS[0], "A", 0.9)], {"A": down})
    assert lost.total_return < -0.003 and lost.max_drawdown > 0.003


def test_no_new_trades_buys_nothing_and_defensive_buys_two():
    bars = {s: flat() for s in "ABCD"}
    picks = [Pick(DAYS[0], s, 1 - i / 10) for i, s in enumerate("ABCD")]
    none = run(picks, bars, modes={DAYS[0]: "NO_NEW_TRADES"})
    assert none.trades == 0 and none.total_return == 0
    two = run(picks, bars, modes={DAYS[0]: "DEFENSIVE"})
    assert two.trades == 2 and two.skipped["market_mode_limit"] == 2


def test_the_strongest_picks_get_the_free_slots():
    bars = {s: flat() for s in "ABCDE"}
    picks = [Pick(DAYS[0], s, sc) for s, sc in zip("ABCDE", (0.1, 0.9, 0.5, 0.8, 0.7), strict=True)]
    r = run(picks, bars, capital=100_000)  # the Rs 1 lakh rung: four positions
    assert r.trades == 4 and r.skipped.get("no_free_slot") == 1


def test_a_tiny_account_cannot_size_a_position_above_the_minimum():
    r = run([Pick(DAYS[0], "A", 0.9)], {"A": flat()}, capital=10_000)
    assert r.trades == 0 and r.skipped["too_small_or_no_cash"] == 1


def test_a_stock_already_held_is_not_bought_twice():
    r = run([Pick(DAYS[0], "A", 0.9), Pick(DAYS[1], "A", 0.9)], {"A": flat()})
    assert r.trades == 1 and r.skipped["already_held"] == 1


def test_a_position_times_out_after_fifteen_bars():
    r = run([Pick(DAYS[0], "A", 0.9)], {"A": flat()})
    assert r.trades == 1
    short = simulate([Pick(DAYS[0], "A", 0.9)], {"A": flat()}, DAYS[:8], capital=500_000)
    assert short.trades == 0 and short.still_open == 1


def test_a_deep_loss_halts_new_buys():
    gap = dict.fromkeys(range(2, 30), (70, 70, 70, 70))  # gaps down 30% and stays there
    bars = {s: flat(overrides=gap) for s in "ABCD"}
    bars["F"] = flat()
    picks = [Pick(DAYS[0], s, 1.0) for s in "ABCD"] + [Pick(DAYS[5], "F", 1.0)]
    r = run(picks, bars, capital=100_000)
    assert r.max_drawdown > 0.15 and r.halted_days > 0
    assert r.skipped["drawdown_halt"] == 1


def test_random_baseline_is_repeatable():
    bars = {s: flat() for s in "ABC"}
    pool = {DAYS[0]: list("ABC"), DAYS[1]: list("ABC")}
    a = random_baseline(pool, {DAYS[0]: 1, DAYS[1]: 1}, bars, DAYS, {}, capital=500_000, draws=5)
    b = random_baseline(pool, {DAYS[0]: 1, DAYS[1]: 1}, bars, DAYS, {}, capital=500_000, draws=5)
    assert a == b and a["return_p5"] <= a["return_p95"]
