"""M05 memory: past cases (outcome, key, when it was known) and recall."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from brain_fakes import FakeReader, make_module, registry
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m05_memory.cases import barrier_outcomes, build_cases, state_keys
from swing_trade_ml.brain.modules.m05_memory.module import Memory
from swing_trade_ml.brain.modules.m05_memory.recall import recall
from swing_trade_ml.brain.runner import execute


def _bars(close, spread=0.01, start="2024-01-01") -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "day": pd.bdate_range(start, periods=len(close)).date,
            "open": close,
            "high": close * (1 + spread),
            "low": close * (1 - spread),
            "close": close,
            "volume": 100_000.0,
        }
    )


def _rate(n, r):
    return 100 * (1 + r) ** np.arange(n)


def test_a_steady_rise_reaches_the_target_on_day_seven():
    out = barrier_outcomes(_bars(_rate(40, 0.01)))
    first = out.iloc[0]
    assert first["outcome"] == "target" and first["days"] == 7 and first["exit_return"] == pytest.approx(0.08)
    assert first["outcome_day"] == _bars(_rate(40, 0.01))["day"].iloc[7]
    assert len(first["path"]) == 15 and first["path"][0] == pytest.approx(0.01)


def test_a_steady_fall_hits_the_stop_first():
    first = barrier_outcomes(_bars(_rate(40, -0.01))).iloc[0]
    assert first["outcome"] == "stop" and first["days"] == 4 and first["exit_return"] == pytest.approx(-0.04)


def test_a_day_touching_both_barriers_counts_as_a_stop():
    bars = _bars(np.full(40, 100.0))
    bars.loc[3, "high"], bars.loc[3, "low"] = 109.0, 95.0
    assert barrier_outcomes(bars).iloc[0]["outcome"] == "stop"


def test_nothing_touched_is_a_timeout_with_the_day_15_return():
    first = barrier_outcomes(_bars(np.full(40, 100.0))).iloc[0]
    assert first["outcome"] == "timeout" and first["days"] == 15 and first["exit_return"] == 0.0
    assert first["outcome_day"] == first["path_day"]


def test_the_last_15_days_have_no_case():
    assert len(barrier_outcomes(_bars(_rate(40, 0.01)))) == 25


def test_state_keys_name_trend_volatility_and_the_stock_label():
    bars = _bars(_rate(260, 0.003))
    market = pd.Series("up-trend", index=bars["day"])
    keys = state_keys(bars, market)
    last = keys.iloc[-1]
    assert last["market"] == "up-trend" and last["stock"] == "up"
    assert last["trend"] == "rising" and last["vol"] == "normal"  # +6% in 20 days; 2% daily range
    assert keys["stock"].iloc[:199].isna().all()  # no 200-day average yet


def test_cases_join_keys_and_outcomes_and_skip_unwarmed_days():
    bars = _bars(_rate(260, 0.003))
    cases = build_cases("ABC", bars, pd.Series("up-trend", index=bars["day"]))
    assert set(cases["symbol"]) == {"ABC"} and len(cases) == 260 - 199 - 15
    assert {
        "day",
        "market",
        "stock",
        "trend",
        "vol",
        "outcome",
        "exit_return",
        "days",
        "outcome_day",
        "path_day",
        "path",
    } <= set(cases.columns)


# --- recall ------------------------------------------------------------------------------------

KEY = {"market": "correction", "stock": "down", "trend": "falling", "vol": "normal"}
AS_OF = date(2026, 9, 1)


def _cases(n, outcome="target", known=AS_OF - timedelta(days=1), **key):
    k = {**KEY, **key}
    ret = {"target": 0.08, "stop": -0.04, "timeout": 0.01}[outcome]
    return pd.DataFrame(
        {
            "symbol": "X",
            "day": [known - timedelta(days=20)] * n,
            **{part: [v] * n for part, v in k.items()},
            "outcome": [outcome] * n,
            "exit_return": [ret] * n,
            "days": [9] * n,
            "outcome_day": [known] * n,
            "path_day": [known] * n,
            "path": [[0.005 * (d + 1) for d in range(15)]] * n,
        }
    )


def test_the_hit_rate_band_and_days_of_exact_matches():
    cases = pd.concat([_cases(12, "target"), _cases(22, "stop"), _cases(6, "timeout")])
    r = recall(cases, "ABC", KEY, AS_OF)
    assert r.n_similar == 40 and r.hit_rate == pytest.approx(0.3) and r.widened == ()
    assert r.median_return == pytest.approx(-0.04) and (r.p25, r.p75) == (
        pytest.approx(-0.04),
        pytest.approx(0.08),
    )
    assert r.median_days == 9
    assert r.typical_path[0] == (1, pytest.approx(0.005), pytest.approx(0.005), pytest.approx(0.005))


def test_cases_not_known_by_as_of_are_excluded():
    cases = pd.concat([_cases(40, "stop"), _cases(40, "target", known=AS_OF + timedelta(days=3))])
    r = recall(cases, "ABC", KEY, AS_OF)
    assert r.n_similar == 40 and r.hit_rate == 0.0


def test_widening_drops_volatility_then_market_and_says_so():
    other_vol = _cases(25, "target", vol="high")
    exact = _cases(10, "stop")
    r = recall(pd.concat([exact, other_vol]), "ABC", KEY, AS_OF)
    assert r.widened == ("volatility",) and r.n_similar == 35
    other_market = _cases(30, "target", vol="high", market="up-trend")
    r2 = recall(pd.concat([_cases(5, "stop"), other_market]), "ABC", KEY, AS_OF)
    assert r2.widened == ("volatility", "market") and r2.n_similar == 35


def test_too_few_cases_even_widened_is_reported_as_is():
    r = recall(_cases(7, "target"), "ABC", KEY, AS_OF)
    assert r.n_similar == 7 and r.widened == ("volatility", "market", "trend")


def test_no_cases_at_all_is_an_empty_recall():
    r = recall(_cases(0), "ABC", KEY, AS_OF)
    assert r.n_similar == 0 and r.hit_rate is None


def test_recall_also_reports_the_honest_figures():
    """46 unseen months: memory's distance from the average came true only
    about a quarter of the time, so the honest figure keeps a quarter of it."""
    similar = pd.concat([_cases(12, "target"), _cases(22, "stop"), _cases(6, "timeout")])
    others = _cases(160, "timeout", stock="up", trend="flat")  # everything else, for the base rate
    r = recall(pd.concat([similar, others]), "ABC", KEY, AS_OF)
    base_hit = 12 / 200
    assert r.hit_rate == pytest.approx(0.3)
    assert r.honest_hit_rate == pytest.approx(base_hit + 0.25 * (0.3 - base_hit))
    mean_similar = (12 * 0.08 - 22 * 0.04 + 6 * 0.01) / 40
    base_mean = (12 * 0.08 - 22 * 0.04 + 166 * 0.01) / 200
    assert r.mean_return == pytest.approx(mean_similar)
    assert r.honest_mean_return == pytest.approx(base_mean + 0.25 * (mean_similar - base_mean))


# --- storage, the module and the nightly rebuild ---------------------------------------------


def _history_cases():
    rows = [
        _cases(30, "target", stock="up", trend="rising"),
        _cases(30, "stop", stock="down", trend="falling"),
    ]
    return pd.concat(rows, ignore_index=True)


class MemoryReader(FakeReader):
    def __init__(self, cases, bars, **kw):
        super().__init__(**kw)
        self.as_of = datetime(2026, 9, 1, 12, tzinfo=UTC)
        self._cases, self._bars_by = cases, bars

    def experience(self):
        return self._cases

    def dated_bars(self, symbol):
        return self._bars_by.get(symbol, _bars([]))


def test_m05_is_the_remember_step_and_starts_on_trial():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M05") is Memory
    m = Memory.manifest
    assert m.step is Step.REMEMBER and m.kind == "step" and m.default_mode is Mode.SHADOW


def test_ideas_and_holdings_get_a_recall_keyed_on_todays_situation():
    rising = _bars(_rate(260, 0.003), start="2025-06-01")
    falling = _bars(_rate(260, -0.003), start="2025-06-01")
    reader = MemoryReader(
        _history_cases(),
        {"ABC": rising, "HELD": falling},
        holdings=(c.Holding(symbol="HELD", qty=1, avg_price=1.0),),
    )
    market = c.Situation(scope="market", subject="NIFTY 50", label="correction", confidence=0.8)

    def recognise(view):
        return c.Contribution(situations=(market,))

    m04 = make_module("M04", Step.RECOGNISE, writes=("Situation@1",), run=recognise)
    req = c.RunRequest(run_id="t", kind="nightly", as_of=reader.as_of, universe=("ABC",), live=True)
    ctx = execute(req, reader, registry(m04, Memory), {"M05": Mode.ON})
    assert ctx.recalls["ABC"].hit_rate == 1.0 and "market correction" in ctx.recalls["ABC"].key
    assert ctx.recalls["HELD"].hit_rate == 0.0  # holdings get one too (M15 needs the path)


def test_a_stock_without_enough_bars_gets_no_recall():
    reader = MemoryReader(_history_cases(), {})
    req = c.RunRequest(run_id="t", kind="nightly", as_of=reader.as_of, universe=("ABC",), live=True)
    ctx = execute(req, reader, registry(Memory), {"M05": Mode.ON})
    assert "ABC" not in ctx.recalls


def test_experience_round_trips_through_the_table(db_session):
    from swing_trade_ml.brain.modules.m05_memory.store import load_experience, sync_experience

    cases = _history_cases()
    cases["day"] = [date(2026, 1, 5) + timedelta(days=i) for i in range(len(cases))]
    assert sync_experience(db_session, cases) == 60
    assert sync_experience(db_session, cases) == 60  # replaced, not doubled
    back = load_experience(db_session, upto=AS_OF)
    assert len(back) == 60 and set(back["outcome"]) == {"target", "stop"}
    assert len(back.iloc[0]["path"]) == 15
    assert load_experience(db_session, upto=date(2026, 1, 1)).empty  # nothing known yet


def test_only_live_nightly_runs_rebuild_the_memory(db_session, monkeypatch):
    from swing_trade_ml.brain import service
    from swing_trade_ml.brain.modules.m05_memory import store

    calls = []
    monkeypatch.setattr(store, "rebuild_from_reader", lambda db, reader: calls.append(reader.live))
    for kind, as_of in (("nightly", None), ("why", None), ("nightly", datetime(2026, 9, 1, 12, tzinfo=UTC))):
        service.run_brain(db_session, kind=kind, as_of=as_of, symbols=["ZZZ"])
    assert calls == [True]
