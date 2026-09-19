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
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.predict import _get_bundle
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.ml.sector_map import get_sector_index
from swing_trade_ml.strategies.base import BaseStrategy, SignalDecision, register_strategy

log = get_logger(__name__)


def _model_reason(model: Any, probability: float) -> str:
    """Describe, in one sentence, the question this model was trained on.

    Branches on `label_kind` because the two say materially different things.
    A barrier model's probability is the chance of reaching the target
    *without first being stopped out*, which is the number a reader should
    act on; an endpoint model's is merely the chance of being higher at the
    horizon, having possibly fallen a long way in between. Printing the
    barrier model's answer in the endpoint's words would overstate it.
    """
    stem = f"{model.name}:{model.version} predicts {probability:.1%} chance of "
    if model.label_kind == "barrier" and model.stop_return_pct is not None:
        return (
            stem + f"+{model.target_return_pct:.1%} before -{model.stop_return_pct:.1%}, "
            f"within {model.prediction_horizon_days} trading days"
        )
    return (
        stem + f"+{model.target_return_pct:.1%} within "
        f"{model.prediction_horizon_days} days"
    )


@register_strategy
class MLSwingStrategy(BaseStrategy):
    strategy_type: ClassVar[str] = "ml_swing"
    display_name: ClassVar[str] = "ML Swing Classifier"
    description: ClassVar[str] = (
        "Buys when the trained classifier's probability of a target move within the "
        "prediction horizon exceeds the confidence threshold, subject to liquidity "
        "and volatility filters. Stop and target are the label's own levels."
    )
    default_params: ClassVar[dict[str, Any]] = {
        "model_name": "swing_classifier",
        # Falls back to settings.ML_MIN_CONFIDENCE when null
        "min_confidence": None,
        # Below this the model is actively signalling weakness — exit
        "exit_confidence": 0.35,
        "min_avg_volume": 100_000,
        # Reject anything moving more than 6% a day annualised into ~95% vol
        "max_volatility": 0.06,
        # NIFTY itself in a downtrend: require extra conviction, since a bear
        # market drags most stocks down regardless of their own setup
        "bear_market_confidence_boost": 0.10,
        # A stock down this much in 5 days is a falling knife, not a dip —
        # the model can't tell "oversold bounce" from "still falling" from
        # price action alone
        "falling_knife_return_5d_pct": -0.08,
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
        # Bounded to this instrument's own most recent visible bar — the same
        # look-ahead guarantee `d` already carries (live: only up-to-now
        # candles; backtest: the caller's pre-sliced window), reused rather
        # than threading a new parameter through evaluate()/BaseStrategy.
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
        atr_value = float(atr(d["high"], d["low"], d["close"], 14).iloc[-1])
        avg_volume = float(d["volume"].rolling(20).mean().iloc[-1])
        daily_vol = float(d["close"].pct_change().rolling(20).std().iloc[-1])

        threshold = self.params.get("min_confidence") or settings.ML_MIN_CONFIDENCE
        # NIFTY's own SMA50/200 cross, from build_features' index context —
        # negative means the broad market itself is in a downtrend.
        nifty_regime = float(row["nifty_trend_regime"].iloc[0])
        bear_market = nifty_regime < 0
        effective_threshold = threshold + (
            float(self.params["bear_market_confidence_boost"]) if bear_market else 0.0
        )
        recent_5d_return = float(d["close"].pct_change(5).iloc[-1])

        features = {
            "probability": round(probability, 4),
            "atr_14": round(atr_value, 2),
            "avg_volume_20": int(avg_volume),
            "daily_volatility_20": round(daily_vol, 4),
            "model": f"{model.name}:{model.version}",
            "threshold": round(effective_threshold, 4),
            "bear_market": bear_market,
            "return_5d": round(recent_5d_return, 4),
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

        if probability < effective_threshold:
            reason = f"Confidence {probability:.1%} below {effective_threshold:.0%} threshold"
            if bear_market:
                reason += " (raised — NIFTY itself is in a downtrend)"
            return SignalDecision(
                signal=SignalType.HOLD,
                price=price,
                confidence=round(probability, 3),
                reason=reason,
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
        if recent_5d_return <= float(self.params["falling_knife_return_5d_pct"]):
            blockers.append(
                f"fell {recent_5d_return:.1%} in 5 days — treating as a falling knife, not a dip"
            )

        if blockers:
            return SignalDecision(
                signal=SignalType.HOLD,
                price=price,
                confidence=round(probability, 3),
                reason=f"Model confident ({probability:.1%}) but filtered: " + "; ".join(blockers),
                features=features,
            )

        # The levels are the label's, not a volatility distance. The model was
        # scored on one question — target reached before stop, inside the
        # horizon — so a position managed to any other pair of levels is a
        # different trade than the one the confidence number describes. An ATR
        # stop made that mismatch a fresh one on every instrument.
        stop_loss = price * (1 - settings.ML_STOP_RETURN_PCT)
        take_profit = price * (1 + settings.ML_TARGET_RETURN_PCT)

        return SignalDecision(
            signal=SignalType.BUY,
            price=price,
            confidence=round(probability, 3),
            reason=_model_reason(model, probability),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            horizon_days=model.prediction_horizon_days,
            features=features,
        )
