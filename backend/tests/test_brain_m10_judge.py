"""M10's pure market judge: v1's regime table, plus FII flows, a crash-day
rule and a second day of confirmation before relaxing."""

from __future__ import annotations

import numpy as np
import pandas as pd

from swing_trade_ml.brain.contracts import MarketMode
from swing_trade_ml.brain.modules.m10_market.judge import MarketInputs, judge


def _walk(n: int, drift: float, seed: int, start: float = 20_000.0, vol: float = 0.006) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(start * np.cumprod(1 + drift + rng.normal(0, vol, n)))


def _inputs(
    *,
    drift: float = 0.001,
    n: int = 320,
    breadth: float | list[float] = 0.5,
    fii: list[float] | None = None,
    last_index_move: float | None = None,
    last_vix_move: float | None = None,
) -> MarketInputs:
    index = _walk(n, drift, seed=1)
    vix = _walk(n, 0.0, seed=2, start=13.0, vol=0.02)
    if last_index_move is not None:
        index.iloc[-1] = index.iloc[-2] * (1 + last_index_move)
    if last_vix_move is not None:
        vix.iloc[-1] = vix.iloc[-2] * (1 + last_vix_move)
    if isinstance(breadth, list):
        series = pd.Series([0.5] * (n - len(breadth)) + breadth)
    else:
        series = pd.Series([breadth] * n)
    return MarketInputs(index_close=index, vix_close=vix, breadth=series, fii_net=fii or [])


def test_a_rising_broad_market_is_normal():
    state = judge(_inputs(breadth=0.65))
    assert state.mode is MarketMode.NORMAL
    assert state.trend == "up" and state.breadth_pct == 0.65


def test_a_falling_market_is_defensive_and_says_why():
    state = judge(_inputs(drift=-0.001))
    assert state.mode is MarketMode.DEFENSIVE
    assert "down-trend" in state.reasons[0]


def test_a_crash_day_means_no_new_trades():
    state = judge(_inputs(breadth=0.65, last_index_move=-0.05))
    assert state.mode is MarketMode.NO_NEW_TRADES
    assert "fell 5%" in state.reasons[0]


def test_a_vix_spike_means_no_new_trades():
    state = judge(_inputs(breadth=0.65, last_vix_move=0.35))
    assert state.mode is MarketMode.NO_NEW_TRADES
    assert "VIX" in state.reasons[0]


def test_fii_selling_turns_a_merely_normal_market_defensive():
    selling = [100.0] * 15 + [-500.0, -400.0, 200.0, -300.0, -600.0]  # 4 of last 5 negative, 20-day sum < 0
    state = judge(_inputs(breadth=0.5, fii=selling))
    assert state.mode is MarketMode.DEFENSIVE
    assert any("FII" in r and "sold" in r for r in state.reasons)
    assert state.fii_net_5d_cr == sum(selling[-5:])


def test_fii_selling_does_not_override_a_strong_broad_market():
    selling = [100.0] * 15 + [-500.0, -400.0, 200.0, -300.0, -600.0]
    assert judge(_inputs(breadth=0.75, fii=selling)).mode is MarketMode.NORMAL


def test_one_good_day_after_a_weak_spell_stays_defensive():
    state = judge(_inputs(breadth=[0.35, 0.65]))  # yesterday narrow (weak), today broad
    assert state.mode is MarketMode.DEFENSIVE
    assert any("second day" in r for r in state.reasons)


def test_two_good_days_relax_to_normal():
    assert judge(_inputs(breadth=[0.35, 0.65, 0.65])).mode is MarketMode.NORMAL


def test_missing_fii_data_is_said_plainly():
    state = judge(_inputs(breadth=0.65))
    assert any("FII flow data is not available" in r for r in state.reasons)
    assert state.fii_net_5d_cr is None


def test_too_little_index_history_cannot_be_judged():
    state = judge(_inputs(n=120))
    assert state.mode is MarketMode.DEFENSIVE and state.trend == "unknown"
    assert "Not enough NIFTY history" in state.reasons[0]
