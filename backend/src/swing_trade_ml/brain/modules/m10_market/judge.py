"""The market brain's judgement: NORMAL, DEFENSIVE or NO NEW TRADES.

Built on version 1's own regime table (`deployable.classify_deployable`:
NIFTY trend and volatility, breadth, India VIX), which the risk rules already
use for how much may be invested. This adds only what that table lacks:

* FII flows — foreign funds selling on 4 of the last 5 days and over the last
  20 turn a merely "normal" market DEFENSIVE. Strong, broad markets are not
  lowered: their breadth already confirms them.
* A crash-day rule — NIFTY down 4% or more, or India VIX up 30% or more, on
  the latest day means NO NEW TRADES.
* Confirmation — turning careful is immediate; relaxing back to NORMAL needs
  the market to look normal on the latest day AND the day before.

Pure: the inputs already end at the run's date.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from swing_trade_ml.brain.contracts import MarketMode, MarketState
from swing_trade_ml.ml.market_context import classify_regime
from swing_trade_ml.services.deployable import PLAIN_REGIME, classify_deployable, latest_percentile

CRASH_INDEX_MOVE = -0.04
CRASH_VIX_MOVE = 0.30
NORMAL_REGIMES = {"normal", "strong", "very_strong"}
_TREND = {"bullish": "up", "bearish": "down"}


@dataclass(frozen=True, slots=True)
class MarketInputs:
    index_close: pd.Series  # NIFTY closes, ascending, ending at the run's date
    vix_close: pd.Series  # India VIX closes, ascending
    breadth: pd.Series  # share of watchlist stocks above their 50-day average, ascending
    fii_net: list[float]  # FII net buying per day (crore), oldest first; may be empty


def _last(series: pd.Series) -> float | None:
    clean = series.dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


def _day_change(series: pd.Series) -> float | None:
    clean = series.dropna()
    if len(clean) < 2 or clean.iloc[-2] == 0:
        return None
    return float(clean.iloc[-1] / clean.iloc[-2] - 1)


def _fii_selling(fii_net: list[float]) -> bool:
    if len(fii_net) < 20:
        return False
    last5 = fii_net[-5:]
    return sum(1 for v in last5 if v < 0) >= 4 and sum(fii_net[-20:]) < 0


def _raw(inputs: MarketInputs) -> tuple[MarketMode, str, list[str]]:
    """Mode, regime name and reasons for the latest day, before confirmation."""
    regime = classify_regime(inputs.index_close)
    trend = regime["regime"]
    breadth = _last(inputs.breadth)
    vix_pct = latest_percentile(inputs.vix_close)
    dep = classify_deployable(trend, regime["volatility_level"], breadth, vix_pct)

    if trend not in _TREND:
        return (
            MarketMode.DEFENSIVE,
            "unknown",
            ["Not enough NIFTY history to judge the market, so the brain stays careful."],
        )

    trend_reason = (
        "NIFTY's 50-day average is above its 200-day average (up-trend)."
        if trend == "bullish"
        else "NIFTY's 50-day average is below its 200-day average (down-trend)."
    )
    context: list[str] = []
    if breadth is not None:
        context.append(f"{breadth:.0%} of watchlist stocks are above their 50-day average.")
    vix = _last(inputs.vix_close)
    if vix is not None and vix_pct is not None:
        context.append(f"India VIX is {vix:.1f}, higher than {vix_pct:.0%} of the past year.")
    if regime["volatility_level"] == "elevated":
        context.append("Market swings are larger than usual.")
    context.append(f"Overall the market looks {PLAIN_REGIME.get(dep.regime, dep.regime)}.")

    if dep.regime in NORMAL_REGIMES:
        if dep.regime == "normal" and _fii_selling(inputs.fii_net):
            reason = (
                "Foreign investors (FIIs) sold on at least 4 of the last 5 days and over the last 20 days."
            )
            return MarketMode.DEFENSIVE, dep.regime, [reason, trend_reason, *context]
        return MarketMode.NORMAL, dep.regime, [trend_reason, *context]

    if trend == "bearish":
        return MarketMode.DEFENSIVE, dep.regime, [trend_reason, *context]
    # Rising trend, but too few stocks are joining in.
    lead = context[0] if breadth is not None else trend_reason
    return MarketMode.DEFENSIVE, dep.regime, [lead, trend_reason, *[c for c in context if c != lead]]


def _trim_last_day(inputs: MarketInputs) -> MarketInputs:
    return MarketInputs(
        index_close=inputs.index_close.iloc[:-1],
        vix_close=inputs.vix_close.iloc[:-1],
        breadth=inputs.breadth.iloc[:-1],
        fii_net=inputs.fii_net[:-1],
    )


def judge(inputs: MarketInputs) -> MarketState:
    regime = classify_regime(inputs.index_close)
    facts = {
        "trend": _TREND.get(regime["regime"], "unknown"),
        "volatility": regime["volatility_level"],
        "breadth_pct": _last(inputs.breadth),
        "vix": _last(inputs.vix_close),
        "fii_net_5d_cr": sum(inputs.fii_net[-5:]) if len(inputs.fii_net) >= 5 else None,
    }
    flow_note = (
        [] if len(inputs.fii_net) >= 5 else ["FII flow data is not available, so flows were not judged."]
    )

    index_move = _day_change(inputs.index_close)
    vix_move = _day_change(inputs.vix_close)
    if index_move is not None and index_move <= CRASH_INDEX_MOVE:
        reason = f"NIFTY fell {abs(index_move):.0%} today — a crash day, so no new buys."
        return MarketState(**facts, mode=MarketMode.NO_NEW_TRADES, reasons=(reason, *flow_note))
    if vix_move is not None and vix_move >= CRASH_VIX_MOVE:
        reason = f"India VIX jumped {vix_move:.0%} today — fear spiked, so no new buys."
        return MarketState(**facts, mode=MarketMode.NO_NEW_TRADES, reasons=(reason, *flow_note))

    mode, _regime_name, reasons = _raw(inputs)
    if mode is MarketMode.NORMAL:
        previous, _, _ = _raw(_trim_last_day(inputs))
        if previous is not MarketMode.NORMAL:
            mode = MarketMode.DEFENSIVE
            reasons = [
                "The market looks better today, but the brain waits for a second day "
                "to confirm before relaxing.",
                *reasons,
            ]
    return MarketState(**facts, mode=mode, reasons=(*reasons, *flow_note))
