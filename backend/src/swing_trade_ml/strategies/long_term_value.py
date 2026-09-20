"""Long-term stock picks — see
docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md.

Phase 1: reuses ml_swing's exact pipeline (same build_features, same
train_model) with a longer horizon and a wider percentage-based stop/target
appropriate to a multi-month hold rather than ATR-based day-to-day noise.
Phase 2 (a follow-up task, gated on docs/superpowers/research/2026-09-12-
fundamentals-vendor-decision.md) layers fundamentals features on top.

No return-multiple promise ("10X" or any number) appears anywhere in this
module's signal text — confidence and a real tracked hit-rate only, same
standard as every other signal in the app.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.features import build_features
from swing_trade_ml.ml.market_context import (
    load_index_candles, load_sector_candles, load_vix_candles, load_market_breadth,
)
from swing_trade_ml.ml.sector_map import get_sector_index
from swing_trade_ml.ml.predict import _get_bundle
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.strategies.base import BaseStrategy, SignalDecision, register_strategy

log = get_logger(__name__)

# 250 trading days (~1 year) — long enough to be a genuinely different
# horizon from the swing model's ~5-20 days, short enough that the model
# still trains on a meaningful number of non-overlapping examples given the
# watchlist's available history.
LONG_TERM_HORIZON_DAYS = 250

# The swing model's DEFAULT_TAKE_PROFIT_PCT is 0.15 (core/config.py) — a
# 1-year hold should target a materially larger move than a 2-week swing,
# not the same one scaled by time. 30% is the starting point; revisit once
# backtested (spec §10 open items).
LONG_TERM_TARGET_RETURN_PCT = 0.30

# Calendar days, and past LONG_TERM_HORIZON_DAYS trading days (~365 calendar)
# on purpose: the time stop is the backstop for a thesis that stopped working,
# not the exit itself. Declared here rather than left to services/exit_policy,
# whose defaults are the swing trade's — inheriting those would book half this
# position at +5% and close it at 30 days, which is a different strategy.
LONG_TERM_TIME_STOP_DAYS = 420


@register_strategy
class LongTermValueStrategy(BaseStrategy):
    strategy_type: ClassVar[str] = "long_term_value"
    display_name: ClassVar[str] = "Long-Term Value"
    description: ClassVar[str] = (
        "Buys when the long-horizon classifier's probability of a large multi-month "
        "move exceeds the confidence threshold. Advisory only — no auto-execution. "
        "Tracked against real outcomes the same as every other signal in this app; "
        "no target return multiple is ever promised."
    )
    default_params: ClassVar[dict[str, Any]] = {
        "model_name": "long_term_value",
        "min_confidence": 0.65,
        # Wider than the swing model's ATR-based stop — a multi-month hold
        # should not be shaken out by ordinary weekly noise. Percentage-of-
        # price, matching sma_crossover.py's simpler convention, not ATR
        # (which is tuned for short-term noise the long horizon doesn't
        # care about).
        "stop_loss_pct": 0.20,
        "take_profit_pct": LONG_TERM_TARGET_RETURN_PCT,
        "horizon_days": LONG_TERM_HORIZON_DAYS,
        # A one-year thesis is not part-booked at the swing trade's +5%.
        "scale_out_at_pct": 0,
        "time_stop_days": LONG_TERM_TIME_STOP_DAYS,
        "min_avg_volume": 100_000,
        # Advisory only by default (spec §3/§6) — the manual-approval trial
        # phase this whole app is still in applies doubly to a multi-month
        # commitment of capital.
        #
        # Enforced by the shared strategy capability policy.
        "advisory_only": True,
    }

    def min_bars_required(self) -> int:
        return 260

    def evaluate(
        self, df: pd.DataFrame, instrument: Instrument, db: Session
    ) -> SignalDecision | None:
        if len(df) < self.min_bars_required():
            return None

        model = get_active_model(db, self.params.get("model_name"))
        if model is None:
            log.warning("long_term_value.no_active_model", strategy=self.config.name)
            return None

        d = df.sort_values("ts").reset_index(drop=True)
        as_of = d["ts"].max()
        index_df = load_index_candles(db, interval="day", upto=as_of)
        sector_df = load_sector_candles(
            db, get_sector_index(instrument.tradingsymbol), interval="day", upto=as_of
        )
        vix_df = load_vix_candles(db, interval="day", upto=as_of)
        breadth_df = load_market_breadth(db, interval="day", upto=as_of)
        featured = build_features(d, index_df, sector_df, vix_df, breadth_df)
        row = featured.iloc[[-1]]

        bundle = _get_bundle(model)
        feature_names: list[str] = bundle["feature_names"]
        x = row[feature_names]
        if x.isna().to_numpy().any():
            return None

        x_scaled = bundle["scaler"].transform(x.to_numpy(dtype="float64"))
        estimator = bundle["estimator"]
        probability = (
            float(estimator.predict_proba(x_scaled)[0, 1])
            if hasattr(estimator, "predict_proba")
            else float(estimator.predict(x_scaled)[0])
        )

        price = float(d["close"].iloc[-1])
        avg_volume = float(d["volume"].rolling(20).mean().iloc[-1])

        threshold = float(self.params["min_confidence"])
        if probability < threshold:
            return SignalDecision(
                signal=SignalType.HOLD,
                price=price,
                confidence=round(probability, 3),
                reason=f"Confidence {probability:.1%} below {threshold:.0%} threshold",
                features={
                    "probability": round(probability, 4),
                    "model": f"{model.name}:{model.version}",
                },
            )

        if avg_volume < float(self.params["min_avg_volume"]):
            return SignalDecision(
                signal=SignalType.HOLD,
                price=price,
                confidence=round(probability, 3),
                reason=(
                    f"Model confident ({probability:.1%}) but 20-day volume "
                    f"{avg_volume:,.0f} too thin"
                ),
                features={"probability": round(probability, 4)},
            )

        stop_loss = round(price * (1 - float(self.params["stop_loss_pct"])), 2)
        take_profit = round(price * (1 + float(self.params["take_profit_pct"])), 2)

        return SignalDecision(
            signal=SignalType.BUY,
            price=price,
            confidence=round(probability, 3),
            reason=(
                f"{model.name}:{model.version} predicts {probability:.1%} confidence of a "
                f"sustained move over the next {self.params['horizon_days']} trading days "
                f"(long-term, advisory)"
            ),
            stop_loss=stop_loss,
            take_profit=take_profit,
            horizon_days=int(self.params["horizon_days"]),
            features={
                "probability": round(probability, 4),
                "model": f"{model.name}:{model.version}",
            },
        )
