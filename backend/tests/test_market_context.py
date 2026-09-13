"""Market regime classification tests.

`classify_regime` is the pure function behind both the /market-data/regime
dashboard endpoint and ml_swing's bear-market threshold boost — pin its
boundary behaviour directly rather than only through the strategy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from swing_trade_ml.ml.market_context import classify_regime


def _close_series(daily_returns: np.ndarray, start: float = 100.0) -> pd.Series:
    return pd.Series(start * np.cumprod(1 + daily_returns))


def test_too_little_history_is_unknown():
    """Under 200 bars there isn't even a reliable SMA200 — must degrade to
    'unknown' rather than compute on a rolling window that's mostly NaN."""
    close = _close_series(np.full(150, 0.001))
    result = classify_regime(close)
    assert result["regime"] == "unknown"
    assert result["volatility_level"] == "unknown"
    assert result["nifty_close"] is None


def test_uptrend_is_bullish():
    close = _close_series(np.full(300, 0.003))
    result = classify_regime(close)
    assert result["regime"] == "bullish"
    assert result["sma_50"] >= result["sma_200"]


def test_downtrend_is_bearish():
    close = _close_series(np.full(300, -0.003))
    result = classify_regime(close)
    assert result["regime"] == "bearish"
    assert result["sma_50"] < result["sma_200"]


def test_equal_smas_count_as_bullish():
    """Boundary: sma50 == sma200 (a perfectly flat series) — the >= in the
    comparison means a flat market reads as bullish, not bearish, since
    nothing is actually declining."""
    close = _close_series(np.zeros(300))
    result = classify_regime(close)
    assert result["regime"] == "bullish"


def test_recent_volatility_spike_is_elevated():
    """Quiet for a long history, then a sharp swing in the most recent 20
    days — the percentile rank of trailing 20d vol should read elevated."""
    quiet = np.full(350, 0.0005)
    stormy = np.tile([0.05, -0.05], 10)
    close = _close_series(np.concatenate([quiet, stormy]))
    result = classify_regime(close)
    assert result["volatility_level"] == "elevated"


def test_recent_calm_after_choppy_history_is_low():
    """Choppy for a long history, then dead flat for the most recent 20
    days — the percentile rank of trailing 20d vol should read low."""
    choppy = np.tile([0.04, -0.04], 165)
    calm = np.zeros(20)
    close = _close_series(np.concatenate([choppy, calm]))
    result = classify_regime(close)
    assert result["volatility_level"] == "low"


def test_not_enough_volatility_history_is_unknown():
    """Between 200 and ~272 bars: enough for a trend regime, not enough for
    a 252-sample volatility percentile — trend and vol must be independent,
    not both gated on the stricter requirement."""
    close = _close_series(np.full(250, 0.001))
    result = classify_regime(close)
    assert result["regime"] != "unknown"
    assert result["volatility_level"] == "unknown"
