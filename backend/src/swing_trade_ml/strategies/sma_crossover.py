"""Rule-based trend-following baseline.

Kept deliberately simple. Its value is as a benchmark: if the ML model cannot
beat a moving-average crossover over six months of paper trading, the model is
not earning its complexity.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.features import adx, rsi
from swing_trade_ml.strategies.base import BaseStrategy, SignalDecision, register_strategy


@register_strategy
class SMACrossoverStrategy(BaseStrategy):
    strategy_type: ClassVar[str] = "sma_crossover"
    display_name: ClassVar[str] = "SMA Crossover"
    description: ClassVar[str] = (
        "Buys when the fast SMA crosses above the slow SMA in a confirmed uptrend; "
        "exits on the reverse cross. Filtered by ADX and RSI."
    )
    default_params: ClassVar[dict[str, Any]] = {
        "short_window": 20,
        "long_window": 50,
        "trend_window": 200,
        # Below this, price is ranging and crossovers whipsaw badly
        "min_adx": 20.0,
        # Refuse entries that are already extended — poor risk/reward
        "max_rsi": 70.0,
        "use_trend_filter": True,
        "volume_confirm": True,
    }

    def min_bars_required(self) -> int:
        return int(self.params["trend_window"]) + 10

    def evaluate(
        self, df: pd.DataFrame, instrument: Instrument, db: Session
    ) -> SignalDecision | None:
        short_w = int(self.params["short_window"])
        long_w = int(self.params["long_window"])
        trend_w = int(self.params["trend_window"])

        if len(df) < self.min_bars_required():
            return None

        d = df.sort_values("ts").reset_index(drop=True)
        close, high, low, volume = d["close"], d["high"], d["low"], d["volume"]

        sma_short = close.rolling(short_w).mean()
        sma_long = close.rolling(long_w).mean()
        sma_trend = close.rolling(trend_w).mean()
        adx_series = adx(high, low, close, 14)
        rsi_series = rsi(close, 14)
        vol_avg = volume.rolling(20).mean()

        price = float(close.iloc[-1])
        # Compare the last two bars: a crossover is an event, not a state. Acting
        # on "fast is above slow" would re-enter every day the trend persists.
        prev_short, prev_long = float(sma_short.iloc[-2]), float(sma_long.iloc[-2])
        last_short, last_long = float(sma_short.iloc[-1]), float(sma_long.iloc[-1])
        last_adx = float(adx_series.iloc[-1])
        last_rsi = float(rsi_series.iloc[-1])
        above_trend = price > float(sma_trend.iloc[-1])
        volume_ok = (
            not self.params["volume_confirm"]
            or float(volume.iloc[-1]) > float(vol_avg.iloc[-1] or 0)
        )

        features = {
            "sma_short": round(last_short, 2),
            "sma_long": round(last_long, 2),
            "adx_14": round(last_adx, 2),
            "rsi_14": round(last_rsi, 2),
            "above_trend_sma": above_trend,
            "volume_confirmed": volume_ok,
        }

        golden_cross = prev_short <= prev_long and last_short > last_long
        death_cross = prev_short >= prev_long and last_short < last_long

        if death_cross:
            return SignalDecision(
                signal=SignalType.EXIT,
                price=price,
                confidence=0.7,
                reason=f"Death cross: SMA{short_w} crossed below SMA{long_w}",
                features=features,
            )

        if golden_cross:
            blockers = []
            if last_adx < float(self.params["min_adx"]):
                blockers.append(f"ADX {last_adx:.1f} below {self.params['min_adx']} (no trend)")
            if last_rsi > float(self.params["max_rsi"]):
                blockers.append(f"RSI {last_rsi:.1f} overbought")
            if self.params["use_trend_filter"] and not above_trend:
                blockers.append(f"price below SMA{trend_w}")
            if not volume_ok:
                blockers.append("volume below 20-day average")

            if blockers:
                return SignalDecision(
                    signal=SignalType.HOLD,
                    price=price,
                    confidence=0.3,
                    reason="Golden cross rejected: " + "; ".join(blockers),
                    features=features,
                )

            stop_pct = self.config.stop_loss_pct or settings.DEFAULT_STOP_LOSS_PCT
            target_pct = self.config.take_profit_pct or settings.DEFAULT_TAKE_PROFIT_PCT
            # Scale confidence with trend strength, capped so a rule-based
            # signal never claims more certainty than the ML model can.
            confidence = min(0.85, 0.5 + (last_adx - 20) / 100)

            return SignalDecision(
                signal=SignalType.BUY,
                price=price,
                confidence=round(confidence, 3),
                reason=(
                    f"Golden cross: SMA{short_w} above SMA{long_w}, "
                    f"ADX {last_adx:.1f}, RSI {last_rsi:.1f}"
                ),
                stop_loss=round(price * (1 - stop_pct), 2),
                take_profit=round(price * (1 + target_pct), 2),
                features=features,
            )

        return SignalDecision(
            signal=SignalType.HOLD,
            price=price,
            confidence=0.0,
            reason="No crossover event",
            features=features,
        )
