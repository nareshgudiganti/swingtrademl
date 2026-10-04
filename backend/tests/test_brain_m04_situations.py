"""M04 situation recognition: market labels, the unknown detector, episodes."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from brain_fakes import FakeReader, make_module, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m04_situations.episodes import episodes_from_labels
from swing_trade_ml.brain.modules.m04_situations.module import SituationRecognition
from swing_trade_ml.brain.modules.m04_situations.novelty import novelty, state_vectors
from swing_trade_ml.brain.modules.m04_situations.rules import label_days, market_situation
from swing_trade_ml.brain.runner import execute

AS_OF_PAST = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _dated(values) -> pd.Series:
    values = np.asarray(values, dtype=float)
    return pd.Series(values, index=pd.bdate_range("2019-01-01", periods=len(values)).date)


def _path(*legs: tuple[int, float], start=10_000.0) -> pd.Series:
    """Daily closes from legs of (days, daily rate)."""
    rates = np.concatenate([np.full(n, r) for n, r in legs])
    return _dated(start * np.cumprod(1 + rates))


def _calm_vix(nifty: pd.Series) -> pd.Series:
    return pd.Series(15.0, index=nifty.index)


def _labels(nifty, vix=None):
    return label_days(nifty, _calm_vix(nifty) if vix is None else vix)["label"]


def test_a_steady_rise_is_an_up_trend_and_not_defensive():
    nifty = _path((400, 0.0005))
    sit = market_situation(nifty, _calm_vix(nifty))
    assert sit.label == "up-trend" and not sit.suggest_defensive
    assert "above its 50-day average" in sit.evidence[0]


def test_flat_is_sideways():
    assert _labels(_path((300, 0.0005), (150, 0.0))).iloc[-1] == "sideways"


def test_seven_percent_off_the_high_is_a_correction():
    labels = _labels(_path((300, 0.0005), (25, -0.003)))
    assert labels.iloc[-1] == "correction"


def test_a_march_2020_style_fall_reads_crash_then_bear_then_recovery():
    nifty = _path((400, 0.0005), (1, -0.05), (19, -0.015), (32, 0.01))
    labels = _labels(nifty)
    crash_day = 400
    assert labels.iloc[crash_day] == "crash" and labels.iloc[crash_day + 2] == "crash"  # holds 3 days
    assert labels.iloc[crash_day + 10] == "bear phase"
    assert labels.iloc[-1] == "recovery"
    sit = market_situation(nifty.iloc[: crash_day + 1], _calm_vix(nifty).iloc[: crash_day + 1])
    assert sit.label == "crash" and sit.suggest_defensive
    assert sit.evidence[0].startswith("NIFTY fell 5.0% on")


def test_a_vix_jump_alone_is_a_crash():
    nifty = _path((400, 0.0005))
    vix = _calm_vix(nifty).copy()
    vix.iloc[-1] = 21.0  # +40% in a day
    sit = market_situation(nifty, vix)
    assert sit.label == "crash" and "India VIX jumped 40%" in sit.evidence[0]


def test_bear_phase_suggests_defensive_and_says_why():
    nifty = _path((400, 0.0005), (30, -0.006))
    sit = market_situation(nifty, _calm_vix(nifty))
    assert sit.label == "bear phase" and sit.suggest_defensive
    assert "below its 1-year high" in sit.evidence[0] and "200-day" in sit.evidence[0]


def test_short_history_is_unlabelled():
    nifty = _path((120, 0.0005))
    sit = market_situation(nifty, _calm_vix(nifty))
    assert sit.label == "unlabelled" and sit.confidence == 0.0 and not sit.suggest_defensive


def test_recovery_says_how_far_it_fell():
    nifty = _path((400, 0.0005), (1, -0.05), (19, -0.015), (32, 0.01))
    sit = market_situation(nifty, _calm_vix(nifty))
    assert sit.evidence[0].startswith("NIFTY is back within 5% of its high after falling 29%")


# --- the unknown-market detector ------------------------------------------------------------


def _random_market(n=700, seed=4):
    rng = np.random.default_rng(seed)
    nifty = _dated(10_000 * np.cumprod(1 + rng.normal(0.0004, 0.009, n)))
    vix = pd.Series(np.clip(15 + rng.normal(0, 1.5, n), 9, None), index=nifty.index)
    return nifty, vix


def test_an_ordinary_day_is_not_unknown():
    nifty, vix = _random_market()
    result = novelty(state_vectors(nifty, vix))
    assert not result.is_unknown and result.threshold > 0
    assert result.nearest_day is not None


def test_a_day_unlike_any_before_is_unknown():
    nifty, vix = _random_market()
    vix.iloc[-1] = 60.0  # fear four times anything seen
    nifty.iloc[-1] = nifty.iloc[-2] * 0.97
    result = novelty(state_vectors(nifty, vix))
    assert result.is_unknown and result.distance > result.threshold
    assert result.line.startswith("Today's market looks unlike any day")


def test_short_history_is_never_unknown():
    nifty, vix = _random_market(n=200)
    vix.iloc[-1] = 60.0
    result = novelty(state_vectors(nifty, vix))
    assert not result.is_unknown and result.threshold is None


# --- market episodes ---------------------------------------------------------------------------


def _labelled(*runs: tuple[str, int]) -> tuple[pd.Series, pd.Series]:
    labels = [name for name, n in runs for _ in range(n)]
    index = pd.bdate_range("2024-01-01", periods=len(labels)).date
    return pd.Series(labels, index=index), pd.Series(np.linspace(100, 110, len(labels)), index=index)


def test_a_label_must_hold_three_days_except_a_crash():
    labels, closes = _labelled(
        ("up-trend", 10),
        ("correction", 1),
        ("up-trend", 1),
        ("correction", 2),
        ("up-trend", 5),
        ("correction", 4),
        ("up-trend", 6),
    )
    eps = episodes_from_labels(labels, closes)
    assert [e.label for e in eps] == ["up-trend", "correction", "up-trend"]
    assert eps[1].start == labels.index[19] and eps[1].end == labels.index[22]
    assert eps[-1].end is None  # still open


def test_a_crash_opens_an_episode_on_its_first_day():
    labels, closes = _labelled(("up-trend", 10), ("crash", 1), ("bear phase", 8))
    eps = episodes_from_labels(labels, closes)
    assert [(e.label, e.days) for e in eps] == [("up-trend", 10), ("crash", 1), ("bear phase", 8)]


def test_episodes_carry_plain_stats_and_skip_unlabelled_days():
    labels, closes = _labelled(("unlabelled", 5), ("up-trend", 10))
    (ep,) = episodes_from_labels(labels, closes)
    assert ep.label == "up-trend" and ep.days == 10
    assert ep.stats["nifty_change"] == pytest.approx(closes.iloc[-1] / closes.iloc[5] - 1)


# --- the module, storage and the run ----------------------------------------------------------


class MarketReader(FakeReader):
    def __init__(self, nifty, vix=None, **kw):
        super().__init__(**kw)
        self._nifty, self._vix = nifty, _calm_vix(nifty) if vix is None else vix

    def dated_closes(self, symbol):
        return self._vix if symbol == "INDIA VIX" else self._nifty


def _module_run(nifty, universe=("ABC", "XYZ"), extra=()):
    reg = registry(SituationRecognition, *extra)
    return execute(request(universe=universe), MarketReader(nifty), reg, {"M04": Mode.ON})


def test_m04_is_the_recognise_step_module_and_starts_on():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M04") is SituationRecognition
    m = SituationRecognition.manifest
    assert m.step is Step.RECOGNISE and m.kind == "step" and m.default_mode is Mode.ON


def test_the_market_gets_one_situation_with_its_evidence():
    ctx = _module_run(_path((400, 0.0005), (30, -0.006)))
    (market,) = [s for s in ctx.situations if s.scope == "market"]
    assert market.subject == "NIFTY 50" and market.label == "bear phase" and market.suggest_defensive
    assert market.evidence[0].startswith("NIFTY is 16.5% below its 1-year high")


def test_each_stock_gets_a_trend_label_and_extended_when_stretched():
    def state(view):
        feats = (("sma_50_ratio", 0.22),)
        return c.Contribution(
            stocks=(c.StockState(symbol="ABC", trend="up"), c.StockState(symbol="XYZ", trend="down")),
            snapshots=(c.Snapshot(symbol="ABC", as_of="d", close=100.0, features=feats),),
        )

    st = make_module("M02", Step.PERCEIVE, writes=("StockState@1", "Snapshot@1"), run=state)
    ctx = _module_run(_path((400, 0.0005)), extra=(st,))
    stocks = {s.subject: s for s in ctx.situations if s.scope == "stock"}
    assert stocks["ABC"].label == "extended" and "22% above its 50-day average" in stocks["ABC"].evidence[0]
    assert stocks["XYZ"].label == "down-trend"


def test_without_nifty_history_the_market_is_unlabelled():
    ctx = _module_run(pd.Series(dtype=float))
    (market,) = [s for s in ctx.situations if s.scope == "market"]
    assert market.label == "unlabelled" and market.confidence == 0.0 and not market.suggest_defensive


def test_episodes_are_stored_and_replaced(db_session):
    from swing_trade_ml.brain.modules.m04_situations.store import market_episodes, sync_market_episodes

    labels, closes = _labelled(("up-trend", 10), ("crash", 1), ("bear phase", 8))
    sync_market_episodes(db_session, episodes_from_labels(labels, closes))
    sync_market_episodes(db_session, episodes_from_labels(labels, closes))  # idempotent
    rows = market_episodes(db_session)
    assert [(r.label, r.end_day is None) for r in rows] == [
        ("bear phase", True),
        ("crash", False),
        ("up-trend", False),
    ]


def test_only_live_nightly_runs_sync_episodes(db_session, monkeypatch):
    from swing_trade_ml.brain import service
    from swing_trade_ml.brain.modules.m04_situations import store

    calls = []
    monkeypatch.setattr(store, "sync_from_reader", lambda db, reader: calls.append(reader.live))
    for kind, as_of in (("nightly", None), ("why", None), ("nightly", AS_OF_PAST)):
        service.run_brain(db_session, kind=kind, as_of=as_of, symbols=["ZZZ"])
    assert calls == [True]
