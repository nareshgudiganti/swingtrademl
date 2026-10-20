"""ps9: the monthly spot check recomputes the brain's stated price claims from raw prices."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pandas as pd

from swing_trade_ml.brain.modules.m12_stock.setups import find_setups
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.services.brain_observatory import pack, spot_check
from swing_trade_ml.services.limits import format_inr

NO_INDEX = pd.Series(dtype=float)


def _flat_then_breakout(n: int = 80) -> pd.DataFrame:
    """Quiet bars at 100 (high 101), then a last bar closing at 105 on twice the volume."""
    close = [100.0] * (n - 1) + [105.0]
    return pd.DataFrame(
        {
            "open": close,
            "high": [101.0] * (n - 1) + [106.0],
            "low": [99.0] * (n - 1) + [100.0],
            "close": close,
            "volume": [1000.0] * (n - 1) + [2000.0],
        }
    )


def _plan_text(close: float, target: float, stop: float) -> str:
    return (
        f"Plan: buy around {format_inr(close - 1)} to {format_inr(close + 1)}, target {format_inr(target)} "
        f"(+8%), stop {format_inr(stop)} (-4%), up to 15 trading days."
    )


def test_a_true_plan_matches_and_a_wrong_target_is_caught():
    bars = _flat_then_breakout()
    good, _ = spot_check.check_decision([_plan_text(105, 113.4, 100.8)], bars, NO_INDEX)
    assert good[0]["ok"], good
    bad, _ = spot_check.check_decision([_plan_text(105, 120.0, 100.8)], bars, NO_INDEX)
    assert not bad[0]["ok"] and "is not +8% of the close" in bad[0]["detail"]


def test_the_brains_own_setup_lines_are_confirmed_by_the_independent_recheck():
    bars = _flat_then_breakout()
    lines = [s.line for s in find_setups(bars)]
    assert any("breakout" in line for line in lines)
    claims, _ = spot_check.check_decision(lines, bars, NO_INDEX)
    assert claims and all(c["ok"] for c in claims), claims


def test_a_breakout_on_the_wrong_volume_is_caught():
    claims, _ = spot_check.check_decision(
        ["Setup: breakout above the 20-day high on 3.0x the usual volume."], _flat_then_breakout(), NO_INDEX
    )
    assert not claims[0]["ok"]


def test_distance_above_the_50_day_average():
    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.004, 0.01, 120))))
    bars = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1000.0})
    true_pct = round(float(close.iloc[-1] / close.rolling(50).mean().iloc[-1] - 1) * 100)
    ok, _ = spot_check.check_decision([f"ABC is {true_pct}% above its 50-day average."], bars, NO_INDEX)
    wrong, _ = spot_check.check_decision(
        [f"ABC is {true_pct + 5}% above its 50-day average."], bars, NO_INDEX
    )
    assert ok[0]["ok"] and not wrong[0]["ok"]


def test_nifty_trend_claim():
    up = pd.Series(np.linspace(100, 200, 260))
    claims, _ = spot_check.check_decision(
        ["NIFTY's 50-day average is above its 200-day average (up-trend)."], _flat_then_breakout(), up
    )
    assert claims[0]["ok"]
    claims, _ = spot_check.check_decision(
        ["NIFTY's 50-day average is below its 200-day average (down-trend)."], _flat_then_breakout(), up
    )
    assert not claims[0]["ok"]


def test_reasons_without_a_price_claim_are_counted_not_checked():
    claims, other = spot_check.check_decision(
        ["The model scores this stock 62% against a buy level of 60%.", "Similar cases: 14"],
        _flat_then_breakout(),
        NO_INDEX,
    )
    assert claims == [] and other == 2


# --- database ---------------------------------------------------------------------------------


def _seed(db):
    inst = Instrument(instrument_token=717171, tradingsymbol="SPOTX", exchange="NSE", is_watchlisted=True)
    db.add(inst)
    db.flush()
    bars = _flat_then_breakout()
    last = date(2026, 1, 30)
    days = [last - timedelta(days=len(bars) - 1 - i) for i in range(len(bars))]
    for d, row in zip(days, bars.itertuples(), strict=True):
        db.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=datetime.combine(d, time(0, 0), tzinfo=IST),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=int(row.volume),
            )
        )
    as_of = datetime(2026, 1, 30, 11, 0, tzinfo=UTC)  # 16:30 IST, after the close
    db.add(BrainRun(id="spot-1", kind="nightly", live=True, status="done", book="paper", as_of=as_of))
    db.flush()
    db.add_all(
        [
            BrainDecision(
                run_id="spot-1",
                symbol="SPOTX",
                kind="idea",
                word="TRADE",
                reasons=[
                    _plan_text(105, 113.4, 100.8),
                    "Setup: breakout above the 20-day high on 2.0x the usual volume.",
                ],
            ),
            BrainDecision(
                run_id="spot-1",
                symbol="SPOTX",
                kind="idea",
                word="WATCH",
                reasons=[_plan_text(105, 130.0, 100.8)],  # a wrong target: must be listed
            ),
        ]
    )
    db.flush()


def test_the_monthly_pack_lists_every_mismatch(db_session):
    _seed(db_session)
    sc = spot_check.spot_check(db_session, date(2026, 1, 1), date(2026, 1, 31))
    assert (sc["decisions"], sc["claims_checked"], sc["claims_true"]) == (2, 3, 2)
    assert [m["claim"] for m in sc["mismatches"]] == ["trade plan levels"]
    # The same month always picks the same decisions.
    again = spot_check.spot_check(db_session, date(2026, 1, 1), date(2026, 1, 31))
    assert [r["decision_id"] for r in again["rows"]] == [r["decision_id"] for r in sc["rows"]]

    report = pack.plain_report(pack.build_pack(db_session, "2026-01", date(2026, 2, 15)))
    assert "## 5. Are the brain's reasons true? (spot check)" in report
    assert "| SPOTX | 2026-01-30 | trade plan levels |" in report
