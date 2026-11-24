# ruff: noqa: E501 (long plain-English test text)
"""#253: with risk evidence missing, no new trade is made (verification tests; nothing here changes the app).

The settled rule (CLAUDE.md principle 5): decisions only move toward caution; a missing M07 risk gate means NO NEW
TRADES; bad or stale data never makes a decision more aggressive; every module has a safe fallback.

What is covered where (the findings note is docs/verification/253-no-trade-missing-risk.md):
  (a) Brain, risk gate missing or failing   -> tests/test_bad_data_drills.py::test_drill_risk_gate_fault_means_no_new_trades
  (b) Brain, stale or missing market data   -> tests/test_bad_data_drills.py::test_db_drill_*  (cited, re-run in the note)
      v1 scan, missing market context        -> below (a reduced deployable band, not zero)
      v1 scan, a STALE candle                -> below: a confirmed gap, pinned as a strict xfail
  (c) drawdown halt                          -> tests/test_portfolio_risk_layer.py::test_halt_rejects_new_entries (cited)
      stale or missing equity snapshots      -> below
  (d) simulation ledger                      -> tests/test_simulation_app_rules.py (cited)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import IST, last_closed_trading_day
from swing_trade_ml.db.models.market import Candle
from swing_trade_ml.services import deployable, engine, risk
from swing_trade_ml.strategies.base import SignalDecision
from test_portfolio_risk_layer import _flat_deployable, _instrument, _snapshot, _strategy


def _entry(db, strat, inst, value: float):
    return risk.check_entry(
        db, mode="paper", instrument_id=inst.id, price=100.0, stop_loss=95.0,
        portfolio_value=value, available_cash=value, strategy=strat,
    )


# ------------------------------------------------------------------------------- (c) the drawdown halt and snapshots


def test_a_stale_equity_snapshot_still_halts_new_entries(db_session, monkeypatch):
    """The snapshot job stopped weeks ago: the last known peak is old, and the halt still measures from it."""
    _flat_deployable(monkeypatch)
    strat, inst = _strategy(db_session, name="s253_stale_snapshot"), _instrument(db_session, "S253STALE")
    _snapshot(db_session, total_value=1_000_000.0, peak_value=1_000_000.0, days_ago=40)
    db_session.commit()
    assert risk.current_drawdown(db_session, "paper", 800_000.0) == pytest.approx(0.2)
    decision = _entry(db_session, strat, inst, 800_000.0)
    assert decision.allowed is False and decision.rule == "DRAWDOWN"


def test_the_halt_blocks_a_buy_with_a_plain_reason_below_the_limit_only(db_session, monkeypatch):
    _flat_deployable(monkeypatch)
    strat, inst = _strategy(db_session, name="s253_halt"), _instrument(db_session, "S253HALT")
    _snapshot(db_session, total_value=1_000_000.0, peak_value=1_000_000.0, days_ago=1)
    db_session.commit()
    decision = _entry(db_session, strat, inst, 840_000.0)  # exactly 16% below the peak: past the 15% limit
    assert (decision.allowed, decision.rule) == (False, "DRAWDOWN")
    assert "below its peak" in decision.reason and "new buys are paused" in decision.reason
    assert _entry(db_session, strat, inst, 900_000.0).rule != "DRAWDOWN"  # 10% below: not halted


def test_no_snapshot_at_all_means_no_known_peak_and_the_halt_cannot_fire(db_session, monkeypatch):
    """OBSERVED LIMIT, not a defect: with no equity snapshot ever written there is no peak to fall from (a fresh
    account), so the halt reads zero whatever the value is. It cannot tell a fresh account from a wiped history.
    Pinned so a change is noticed; the findings note raises it for the owner."""
    _flat_deployable(monkeypatch)
    monkeypatch.setattr("swing_trade_ml.services.portfolio.trial_start", lambda mode: None)
    assert risk.drawdown_peak(db_session, "paper") is None
    assert risk.current_drawdown(db_session, "paper", 500_000.0) == 0.0
    strat, inst = _strategy(db_session, name="s253_nosnap"), _instrument(db_session, "S253NOSNAP")
    assert _entry(db_session, strat, inst, 500_000.0).rule != "DRAWDOWN"


def test_no_snapshot_at_all_with_the_paper_trial_date_set_also_reads_no_peak(db_session, monkeypatch):
    """Production runs with PAPER_TRIAL_START_DATE set (the trial's own peak, `_trial_peak`). With no snapshot at all the
    trial path also finds no peak, so the same limit holds on BOTH paths. With one snapshot from before the trial (its
    opening equity) the halt fires again: the control."""
    _flat_deployable(monkeypatch)
    monkeypatch.setattr(settings, "PAPER_TRIAL_START_DATE", date(2026, 9, 28))
    assert risk.drawdown_peak(db_session, "paper") is None
    assert risk.current_drawdown(db_session, "paper", 500_000.0) == 0.0
    strat, inst = _strategy(db_session, name="s253_nosnap_trial"), _instrument(db_session, "S253NOSNAPT")
    assert _entry(db_session, strat, inst, 500_000.0).rule != "DRAWDOWN"
    _snapshot(db_session, total_value=1_000_000.0, peak_value=1_000_000.0, days_ago=120)  # before 28 Sep 2026
    db_session.commit()
    assert risk.drawdown_peak(db_session, "paper") == pytest.approx(1_000_000.0)
    assert _entry(db_session, strat, inst, 800_000.0).rule == "DRAWDOWN"


# ------------------------------------------------------------------------------- (b) v1 scan: market context


def test_missing_market_context_reduces_what_v1_may_deploy_it_does_not_raise_it(db_session):
    """No index, breadth or VIX history at all: the entry check falls back to the 'weak' band, never a bolder one."""
    got = deployable.current_deployable(db_session)
    assert got.context_available is False and got.regime == "unknown"
    assert got.fraction == deployable.UNKNOWN_FRACTION == deployable.BANDS["weak"]
    assert got.fraction < deployable.BANDS["normal"] < deployable.BANDS["strong"]


def test_a_failure_while_reading_market_context_falls_back_to_the_same_cautious_band(db_session, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("context unreadable")

    monkeypatch.setattr("swing_trade_ml.ml.market_context.load_index_candles", boom)
    got = deployable.current_deployable(db_session)
    assert (got.regime, got.fraction, got.context_available) == ("unknown", deployable.UNKNOWN_FRACTION, False)


# ------------------------------------------------------------------------------- (b) v1 scan: a stale candle


class _BuyEverything:
    """A stand-in strategy: whatever candles it is handed, it says BUY. It records the age of the newest candle."""

    def __init__(self):
        self.newest: list = []

    def min_bars_required(self) -> int:
        return 1

    def evaluate(self, df, instrument, db):
        self.newest.append(df["ts"].max())
        return SignalDecision(signal="BUY", price=float(df["close"].iloc[-1]), confidence=0.9, reason="stub", features={})


def _scan_with_newest_candle_on(db, monkeypatch, newest_day):
    strat = _strategy(db, name=f"s253_scan_{newest_day}")
    inst = _instrument(db, f"S253SCAN{newest_day:%m%d}")
    for i in range(5):
        day = newest_day - timedelta(days=4 - i)
        db.add(Candle(instrument_id=inst.id, interval="day", ts=datetime(day.year, day.month, day.day, tzinfo=IST), open=100, high=101, low=99, close=100, volume=1000))
    db.commit()
    stub, handed = _BuyEverything(), []
    monkeypatch.setattr(engine, "get_strategy", lambda s: stub)
    monkeypatch.setattr(engine, "eligible_instruments", lambda d, s: [inst])
    monkeypatch.setattr(engine, "process_decision", lambda d, s, i, dec, **kw: handed.append(dec) or None)
    monkeypatch.setattr(engine, "_buy_slot_budget", lambda d, s, m: 5)
    result = engine.run_strategy(db, strat)
    return result, handed


def test_a_fresh_candle_reaches_the_order_path_control(db_session, monkeypatch):
    fresh = last_closed_trading_day(datetime.now(UTC))
    _result, handed = _scan_with_newest_candle_on(db_session, monkeypatch, fresh)
    assert len(handed) == 1  # the control: a candle of the last closed session is scanned and its BUY goes on


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#344/#353): the v1 scan scores the newest stored candle however old it is, and hands its BUY to the order path",
)
def test_a_stale_candle_must_not_feed_a_v1_buy(db_session, monkeypatch):
    """Uses a STUB strategy that says BUY to anything: it proves the ENGINE hands a stale bar's BUY on. That the real
    ml_swing strategy would score such a bar rests on the next test and on `strategies/ml_swing.py:107`."""
    stale = last_closed_trading_day(datetime.now(UTC)) - timedelta(days=12)
    result, handed = _scan_with_newest_candle_on(db_session, monkeypatch, stale)
    assert handed == [] and result.signals_generated == 0


def _real_ml_swing_decision(db, monkeypatch, newest_day):
    """The REAL MLSwingStrategy.evaluate on 300 bars ending `newest_day`, with the trained model and the market-context
    loaders replaced by fixed stand-ins (no model file or index history needed). Returns its decision."""
    import numpy as np
    import pandas as pd

    from swing_trade_ml.strategies import ml_swing

    days = [newest_day - timedelta(days=299 - i) for i in range(300)]
    df = pd.DataFrame(
        {
            "ts": [datetime(d.year, d.month, d.day, tzinfo=IST) for d in days],
            "open": [100.0 + 0.01 * i for i in range(300)],
            "high": [101.0 + 0.01 * i for i in range(300)],
            "low": [99.0 + 0.01 * i for i in range(300)],
            "close": [100.0 + 0.01 * i + (0.2 if i % 2 else 0.0) for i in range(300)],
            "volume": [250_000] * 300,
        }
    )

    class Bundle:
        pass

    class Estimator:
        def predict_proba(self, x):
            return np.array([[0.05, 0.95]])

    class Scaler:
        def transform(self, x):
            return x

    bundle = {"feature_names": ["f"], "scaler": Scaler(), "estimator": Estimator()}
    model = SimpleNamespace(
        name="swing_classifier", version="v-test", prediction_horizon_days=15, label_kind="barrier",
        target_return_pct=0.08, stop_return_pct=0.04,
    )
    empty = pd.DataFrame(columns=["ts", "close"])
    monkeypatch.setattr(ml_swing, "get_active_model", lambda db_, name: model)
    monkeypatch.setattr(ml_swing, "_get_bundle", lambda m: bundle)
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles", "load_market_breadth"):
        monkeypatch.setattr(ml_swing, loader, lambda *a, **k: empty)
    monkeypatch.setattr(
        ml_swing,
        "build_features",
        lambda d, *a, **k: pd.DataFrame({"f": [1.0] * len(d), "nifty_trend_regime": [1.0] * len(d)}),
    )
    strat = _strategy(db, name=f"s253_real_{newest_day}")
    inst = _instrument(db, f"S253REAL{newest_day:%m%d}")
    return ml_swing.MLSwingStrategy(strat).evaluate(df, inst, db)


def test_the_real_ml_swing_strategy_says_buy_on_a_fresh_bar_control(db_session, monkeypatch):
    fresh = last_closed_trading_day(datetime.now(UTC))
    decision = _real_ml_swing_decision(db_session, monkeypatch, fresh)
    assert decision is not None and decision.signal == "BUY"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#344/#353): the real ml_swing strategy scores a 12-day-old newest bar and says BUY (strategies/ml_swing.py:107)",
)
def test_the_real_ml_swing_strategy_must_not_say_buy_on_a_stale_bar(db_session, monkeypatch):
    stale = last_closed_trading_day(datetime.now(UTC)) - timedelta(days=12)
    decision = _real_ml_swing_decision(db_session, monkeypatch, stale)
    assert decision is None or decision.signal != "BUY"
