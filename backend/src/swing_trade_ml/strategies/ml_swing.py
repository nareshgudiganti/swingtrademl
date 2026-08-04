"""ML-driven swing strategy — the primary signal generator.

Takes the active model's probability and turns it into an actionable decision.
Two things it deliberately does *not* do:

* Trade on probability alone. The model is trained on price patterns, not on
  liquidity or volatility regime, so hard filters still apply on top.
* Size the trade. Stops are derived from ATR here because that is a property of
  the instrument; how much capital to commit is the risk service's call.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.features import atr, build_features
from swing_trade_ml.ml.predict import _get_bundle
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.strategies.base import BaseStrategy, SignalDecision, register_strategy

log = get_logger(__name__)


@register_strategy
class MLSwingStrategy(BaseStrategy):
    strategy_type: ClassVar[str] = "ml_swing"
    display_name: ClassVar[str] = "ML Swing Classifier"
    description: ClassVar[str] = (
        "Buys when the trained classifier's probability of a target move within the "
        "prediction horizon exceeds the confidence threshold, subject to liquidity "
        "and volatility filters. ATR-based stops."
    )
    default_params: ClassVar[dict[str, Any]] = {
        "model_name": "swing_classifier",
        # Falls back to settings.ML_MIN_CONFIDENCE when null
        "min_confidence": None,
        # Below this the model is actively signalling weakness — exit
        "exit_confidence": 0.35,
        # Stop at 2x ATR: wide enough to survive normal daily noise, which a
        # fixed percentage stop is not on volatile mid-caps
        "atr_stop_multiplier": 2.0,
        "atr_target_multiplier": 4.0,
        "min_avg_volume": 100_000,
        # Reject anything moving more than 6% a day annualised into ~95% vol
        "max_volatility": 0.06,
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
            log.warning("ml_swing.no_active_model", strategy=self.config.name)
            return None

        d = df.sort_values("ts").reset_index(drop=True)
        featured = build_features(d)
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
        atr_value = float(atr(d["high"], d["low"], d["close"], 14).iloc[-1])
        avg_volume = float(d["volume"].rolling(20).mean().iloc[-1])
        daily_vol = float(d["close"].pct_change().rolling(20).std().iloc[-1])

        threshold = self.params.get("min_confidence") or settings.ML_MIN_CONFIDENCE
        features = {
            "probability": round(probability, 4),
            "atr_14": round(atr_value, 2),
            "avg_volume_20": int(avg_volume),
            "daily_volatility_20": round(daily_vol, 4),
            "model": f"{model.name}:{model.version}",
            "threshold": threshold,
        }

        if probability <= float(self.params["exit_confidence"]):
            return SignalDecision(
                signal=SignalType.EXIT,
                price=price,
                confidence=round(1 - probability, 3),
                reason=(
                    f"Model confidence fell to {probability:.1%} "
                    f"(exit below {float(self.params['exit_confidence']):.0%})"
                ),
                features=features,
            )

        if probability < threshold:
            return SignalDecision(
                signal=SignalType.HOLD,
                price=price,
                confidence=round(probability, 3),
                reason=f"Confidence {probability:.1%} below {threshold:.0%} threshold",
                features=features,
            )

        # Liquidity and volatility filters. Applied after the model, not before,
        # so a rejection is recorded with the probability attached — useful for
        # judging later whether the filters cost anything.
        blockers = []
        if avg_volume < float(self.params["min_avg_volume"]):
            blockers.append(f"20-day volume {avg_volume:,.0f} too thin")
        if daily_vol > float(self.params["max_volatility"]):
            blockers.append(f"daily volatility {daily_vol:.1%} too high")
        if atr_value <= 0:
            blockers.append("ATR unavailable")

        if blockers:
            return SignalDecision(
                signal=SignalType.HOLD,
                price=price,
                confidence=round(probability, 3),
                reason=f"Model confident ({probability:.1%}) but filtered: " + "; ".join(blockers),
                features=features,
            )

        stop_loss = price - float(self.params["atr_stop_multiplier"]) * atr_value
        take_profit = price + float(self.params["atr_target_multiplier"]) * atr_value

        # A stop wider than the configured maximum would risk more per trade
        # than the risk model allows; clamp rather than skip the trade.
        max_stop = price * (1 - (self.config.stop_loss_pct or settings.DEFAULT_STOP_LOSS_PCT) * 2)
        stop_loss = max(stop_loss, max_stop)

        return SignalDecision(
            signal=SignalType.BUY,
            price=price,
            confidence=round(probability, 3),
            reason=(
                f"{model.name}:{model.version} predicts {probability:.1%} chance of "
                f"+{model.target_return_pct:.1%} within {model.prediction_horizon_days} days"
            ),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            features=features,
        )
