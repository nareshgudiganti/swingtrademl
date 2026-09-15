"""How much of the account may be invested at all, given the market right now.

Position limits say how big one trade may be; this says how much of the
account may be in the market in total. Without it the book is fully invested
whenever signals exist — which is exactly when a broad sell-off does the most
damage, because a momentum-flavoured model produces the most signals in the
tape just before one turns.

Deliberately a fixed rule table, not a learned model: five years of daily
history contains only a handful of genuine regime transitions, far too few to
fit a model to without it memorising them. A rule the owner can read is also
a rule the owner can argue with.

Inputs are the market-context series the ML features already use
(ml/market_context.py), so this reads the same picture of the market the model
does, with the same once-a-day cache refresh:

* trend     — NIFTY 50's 50-day average above/below its 200-day average
              (`classify_regime`'s "bullish"/"bearish").
* volatility — NIFTY's 20-day realised volatility against its own past year
              (`classify_regime`'s "low"/"normal"/"elevated").
* breadth   — share of watchlist stocks above their own 50-day average.
* VIX       — INDIA VIX's latest close ranked against its past year.

The mapping (first matching row wins):

| Regime       | Rule                                                          | Deployable |
| ------------ | ------------------------------------------------------------- | ---------- |
| stressed     | falling trend AND (volatility elevated, VIX in top 20%, or    | 10%        |
|              | fewer than 30% of stocks above their 50-day average)          |            |
| weak         | falling trend; or rising trend with fewer than 40% of stocks  | 30%        |
|              | above their 50-day average                                    |            |
| very strong  | rising trend, at least 70% of stocks above their 50-day       | 85%        |
|              | average, and the market calm (volatility low or VIX in the    |            |
|              | bottom 30%)                                                   |            |
| strong       | rising trend, at least 55% of stocks above their 50-day       | 75%        |
|              | average, volatility not elevated                              |            |
| normal       | rising trend, anything else                                   | 55%        |
| unknown      | trend cannot be read (too little index history)               | 30%        |

A missing breadth or VIX reading does not make the regime unknown — the
trend is the anchor — but it can never *raise* the band: "strong" and "very
strong" both require a breadth reading, and "calm" requires a volatility or
VIX reading. When the trend itself is unreadable the fallback is the "weak"
band, not "normal": being wrong by holding cash costs a little upside, being
wrong by being fully invested into a falling market costs capital.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

BANDS: dict[str, float] = {
    "stressed": 0.10,
    "weak": 0.30,
    "normal": 0.55,
    "strong": 0.75,
    "very_strong": 0.85,
}
UNKNOWN_FRACTION = BANDS["weak"]

PLAIN_REGIME: dict[str, str] = {
    "stressed": "under stress",
    "weak": "weak",
    "normal": "normal",
    "strong": "strong",
    "very_strong": "very strong",
    "unknown": "unclear (not enough market data to judge)",
}


@dataclass(frozen=True, slots=True)
class DeployableCapital:
    regime: str
    fraction: float
    context_available: bool

    @property
    def plain_regime(self) -> str:
        return PLAIN_REGIME.get(self.regime, self.regime)


def classify_deployable(
    trend: str,
    volatility_level: str = "unknown",
    breadth_above_sma50: float | None = None,
    vix_percentile: float | None = None,
) -> DeployableCapital:
    """Pure: map market context to a regime and a deployable fraction. See the
    module docstring for the table."""
    if trend not in ("bullish", "bearish"):
        return DeployableCapital("unknown", UNKNOWN_FRACTION, context_available=False)

    elevated = volatility_level == "elevated" or (
        vix_percentile is not None and vix_percentile >= 0.80
    )
    calm = volatility_level == "low" or (vix_percentile is not None and vix_percentile <= 0.30)
    narrow = breadth_above_sma50 is not None and breadth_above_sma50 < 0.40

    if trend == "bearish":
        if elevated or (breadth_above_sma50 is not None and breadth_above_sma50 < 0.30):
            regime = "stressed"
        else:
            regime = "weak"
    elif narrow:
        regime = "weak"
    elif breadth_above_sma50 is not None and breadth_above_sma50 >= 0.70 and calm and not elevated:
        regime = "very_strong"
    elif breadth_above_sma50 is not None and breadth_above_sma50 >= 0.55 and not elevated:
        regime = "strong"
    else:
        regime = "normal"

    return DeployableCapital(regime, BANDS[regime], context_available=True)


def latest_percentile(close: pd.Series, window: int = 252) -> float | None:
    """Where the latest value sits within its own trailing `window`, 0..1.
    None with less than a full window — a percentile of a few weeks is noise."""
    series = close.dropna()
    if len(series) < window:
        return None
    recent = series.iloc[-window:]
    return float((recent <= recent.iloc[-1]).mean())


def current_deployable(db: Session) -> DeployableCapital:
    """Read the market context and classify it. Never raises: an entry check
    must not crash because a context index is missing, so any failure falls
    back to the conservative band and is logged."""
    from swing_trade_ml.ml.market_context import (
        classify_regime,
        load_index_candles,
        load_market_breadth,
        load_vix_candles,
    )

    try:
        index_df = load_index_candles(db)
        close = index_df["close"] if not index_df.empty else pd.Series(dtype=float)
        regime = classify_regime(close)

        breadth: float | None = None
        breadth_df = load_market_breadth(db)
        if not breadth_df.empty:
            values = pd.to_numeric(breadth_df["breadth_pct_above_sma50"], errors="coerce").dropna()
            if not values.empty:
                breadth = float(values.iloc[-1])

        vix_df = load_vix_candles(db)
        vix_pct = latest_percentile(vix_df["close"]) if not vix_df.empty else None
    except Exception as exc:  # noqa: BLE001 — see docstring
        log.warning("deployable.context_failed", error=str(exc))
        return DeployableCapital("unknown", UNKNOWN_FRACTION, context_available=False)

    result = classify_deployable(regime["regime"], regime["volatility_level"], breadth, vix_pct)
    if not result.context_available:
        log.warning("deployable.context_unavailable", fallback_fraction=UNKNOWN_FRACTION)
    return result
