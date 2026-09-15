"""Feature engineering for swing-trade classification.

All indicators are computed with pandas/numpy directly rather than pulling in a
TA library, so the exact formula for every feature is visible and pinned here.

The rule every function obeys: a feature at row *t* uses only data up to and
including *t*. Any accidental use of future data (a centred rolling window, a
backward fill, a global mean) produces a model that scores brilliantly in
backtest and loses money live. That is the single most common way an ML trading
project fails, so the constraint is enforced deliberately rather than assumed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Ordered feature list — the model consumes columns in exactly this order.
# It is persisted alongside every artifact so inference can never silently
# reorder or drop a column.
FEATURE_COLUMNS: list[str] = [
    # trend
    "sma_10_ratio", "sma_20_ratio", "sma_50_ratio", "sma_200_ratio",
    "ema_12_ratio", "ema_26_ratio",
    "sma_10_50_cross", "sma_50_200_cross",
    # momentum
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "stoch_k", "stoch_d", "williams_r", "roc_10", "roc_20",
    # volatility
    "atr_14_pct", "bb_position", "bb_width", "volatility_20",
    # volume
    "volume_ratio_20", "obv_slope", "mfi_14",
    # price structure
    "return_1d", "return_5d", "return_10d", "return_20d",
    "high_20_dist", "low_20_dist", "high_52w_dist",
    "gap_pct", "body_pct", "upper_wick_pct", "lower_wick_pct",
    "days_since_52w_high", "days_since_52w_low", "streak",
    # regime
    "adx_14", "trend_strength", "volatility_percentile_rank",
    # volume (continued)
    "cmf_20",
    # market context — this stock vs. the benchmark index (see market_context.py)
    # nifty_above_200sma deliberately dropped: 0.638 correlated with
    # nifty_trend_regime on the pooled dataset (both a crude "is the market
    # bullish" flag), and with only ~4 years of index history the model sees
    # too few real regime transitions to justify two near-duplicate copies.
    "relative_strength_5d", "relative_strength_20d", "nifty_volatility_20",
    "nifty_trend_regime",
    # sector context — this stock vs. its own sector index (ml/sector_map.py).
    # Same construction as the benchmark ones above, against a narrower peer
    # group: a stock can outperform a falling market while still lagging its
    # own sector, which the benchmark-only comparison can't see.
    "sector_relative_strength_5d", "sector_relative_strength_20d",
    "sector_trend_regime",
    # macro — INDIA VIX, India's own implied-volatility index. Regime-relative
    # (a percentile rank, like volatility_percentile_rank), not the raw level,
    # so it means the same thing whether VIX has structurally drifted up or
    # down over the training window.
    "vix_change_5d", "vix_percentile_rank",
    # market breadth — cross-sectional, computed once across the whole
    # watchlist (see market_context.load_market_breadth), not from this
    # stock's own price at all. Already a 0-1 fraction, so no further
    # normalisation is needed to keep it level-invariant.
    "breadth_pct_above_sma50", "breadth_advance_pct",
]


def _rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing — the averaging RSI, ATR and ADX are defined with.

    A plain rolling mean gives visibly different values for these indicators,
    so the distinction matters for comparability with charting platforms.
    """
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = _rma(gain, period) / _rma(loss, period).replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return _rma(tr, period)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Trend strength, direction-agnostic. Used as a regime filter: mean-reversion
    and breakout signals behave very differently above/below ADX 25."""
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)

    tr = atr(high, low, close, period)
    plus_di = 100 * _rma(plus_dm, period) / tr.replace(0, np.nan)
    minus_di = 100 * _rma(minus_dm, period) / tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _rma(dx, period)


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3
) -> tuple[pd.Series, pd.Series]:
    lowest = low.rolling(k).min()
    highest = high.rolling(k).max()
    k_line = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    return k_line, k_line.rolling(d).mean()


def money_flow_index(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 14
) -> pd.Series:
    """Volume-weighted RSI. Distinguishes a move backed by participation from
    a drift on thin volume — directly relevant when sizing swing entries."""
    typical = (high + low + close) / 3
    raw_flow = typical * volume
    direction = typical.diff()
    pos = raw_flow.where(direction > 0, 0.0).rolling(period).sum()
    neg = raw_flow.where(direction < 0, 0.0).rolling(period).sum()
    ratio = pos / neg.replace(0, np.nan)
    return 100 - (100 / (1 + ratio))


def on_balance_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()


def chaikin_money_flow(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 20
) -> pd.Series:
    """Volume-weighted measure of where each bar closed within its own range —
    a different volume/price construction from OBV and MFI (location-within-bar
    rather than direction-of-close), so it can disagree with them usefully."""
    money_flow_multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    money_flow_volume = money_flow_multiplier * volume
    return money_flow_volume.rolling(period).sum() / volume.rolling(period).sum().replace(0, np.nan)


def _days_since_extreme(values: pd.Series, window: int, kind: str) -> pd.Series:
    """Bars since the rolling window's max (kind="max") or min (kind="min") was
    last set — recency of an extreme, which a pure distance measure (like
    high_52w_dist) cannot express: a stock 1% off its high made yesterday and
    one 1% off a high made eight months ago look identical to a distance-only
    feature but mean very different things.

    Vectorised via a strided window view + argmax/argmin rather than a pandas
    .rolling().apply() — this runs inside services/backtest.py's day-by-day
    loop, which recomputes the full feature set on a growing window every
    simulated day, so a slow per-row Python callback here would compound.
    """
    arr = values.to_numpy(dtype="float64")
    n = len(arr)
    out = np.full(n, np.nan)
    if n < window:
        return pd.Series(out, index=values.index)

    windows = np.lib.stride_tricks.sliding_window_view(arr, window)
    idx = np.nanargmax(windows, axis=1) if kind == "max" else np.nanargmin(windows, axis=1)
    out[window - 1 :] = (window - 1) - idx
    return pd.Series(out, index=values.index)


def _index_context_frame(index_df: pd.DataFrame, prefix: str = "nifty") -> pd.DataFrame:
    """An index-like instrument's own return/regime series, computed once and
    merged onto a stock's frame by ts. Kept separate from build_features'
    main body so it's easy to see this is the only place a second
    instrument's data enters the pipeline.

    `prefix` parametrises which peer group this is: the primary benchmark
    ("nifty", the default — column names stay exactly what they were before
    sector context existed) or a stock's own sector index ("sector"). Same
    formulas either way; only the column names and the merge target's return
    horizon differ per caller.
    """
    idx = index_df.sort_values("ts").reset_index(drop=True)
    close = idx["close"]

    ctx = pd.DataFrame({"ts": idx["ts"]})
    ctx[f"_{prefix}_return_5d"] = close.pct_change(5)
    ctx[f"_{prefix}_return_20d"] = close.pct_change(20)
    ctx[f"{prefix}_volatility_20"] = close.pct_change().rolling(20).std() * np.sqrt(252)

    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    ctx[f"{prefix}_trend_regime"] = np.sign((sma50 / sma200 - 1).fillna(0))
    return ctx


def _vix_context_frame(vix_df: pd.DataFrame) -> pd.DataFrame:
    """INDIA VIX's own regime-relative series, merged onto a stock's frame by
    ts the same way the index/sector context is."""
    vix = vix_df.sort_values("ts").reset_index(drop=True)
    close = vix["close"]

    ctx = pd.DataFrame({"ts": vix["ts"]})
    ctx["vix_change_5d"] = close.pct_change(5)
    ctx["vix_percentile_rank"] = close.rolling(252).rank(pct=True)
    return ctx


def build_features(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    breadth_df: pd.DataFrame,
) -> pd.DataFrame:
    """Attach every column in FEATURE_COLUMNS to an OHLCV frame.

    Expects columns: ts, open, high, low, close, volume — ascending by ts.

    `index_df`, `sector_df`, `vix_df`, `breadth_df` are all required — not
    optional — because a forgotten call site here fails loudly (a TypeError
    at the call, before any model ever sees a row) rather than silently: the
    alternative (an optional parameter defaulting to missing columns) was
    rejected specifically because ml_swing.py's evaluate() logs nothing on
    NaN features, so a forgotten wire-up there would have silently zeroed out
    signal generation forever with no trace in the logs. Fetch them via
    ml.market_context's load_index_candles() / load_sector_candles()
    (sector chosen per-symbol via ml.sector_map.get_sector_index()) /
    load_vix_candles() / load_market_breadth().

    Level-invariant by design: raw prices and moving averages are never fed to
    the model directly, only ratios and percentages. A model trained on the
    absolute price of a Rs 3,000 stock learns nothing transferable to a Rs 200
    one, and would break the moment a stock splits.
    """
    out = df.copy().sort_values("ts").reset_index(drop=True)

    close, high, low = out["close"], out["high"], out["low"]
    open_, volume = out["open"], out["volume"]

    # --- trend: position relative to moving averages -------------------------
    for period in (10, 20, 50, 200):
        sma = close.rolling(period).mean()
        out[f"sma_{period}_ratio"] = close / sma - 1
    for period in (12, 26):
        ema = close.ewm(span=period, adjust=False).mean()
        out[f"ema_{period}_ratio"] = close / ema - 1

    sma10, sma50, sma200 = (close.rolling(p).mean() for p in (10, 50, 200))
    out["sma_10_50_cross"] = sma10 / sma50 - 1
    out["sma_50_200_cross"] = sma50 / sma200 - 1

    # --- momentum ------------------------------------------------------------
    out["rsi_14"] = rsi(close, 14)
    macd_line, macd_sig, macd_hist = macd(close)
    # Normalised by price so MACD is comparable across instruments
    out["macd"] = macd_line / close
    out["macd_signal"] = macd_sig / close
    out["macd_hist"] = macd_hist / close

    k_line, d_line = stochastic(high, low, close)
    out["stoch_k"] = k_line
    out["stoch_d"] = d_line

    highest_14 = high.rolling(14).max()
    lowest_14 = low.rolling(14).min()
    out["williams_r"] = -100 * (highest_14 - close) / (highest_14 - lowest_14).replace(0, np.nan)

    out["roc_10"] = close.pct_change(10)
    out["roc_20"] = close.pct_change(20)

    # --- volatility ----------------------------------------------------------
    atr_14 = atr(high, low, close, 14)
    out["atr_14_pct"] = atr_14 / close

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper, bb_lower = bb_mid + 2 * bb_std, bb_mid - 2 * bb_std
    out["bb_position"] = (close - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)
    out["bb_width"] = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)

    daily_ret = close.pct_change()
    out["volatility_20"] = daily_ret.rolling(20).std() * np.sqrt(252)

    # --- volume --------------------------------------------------------------
    out["volume_ratio_20"] = volume / volume.rolling(20).mean().replace(0, np.nan)
    obv = on_balance_volume(close, volume)
    # Slope as a fraction of its own level — scale-free across instruments
    out["obv_slope"] = obv.diff(10) / obv.rolling(20).mean().abs().replace(0, np.nan)
    out["mfi_14"] = money_flow_index(high, low, close, volume, 14)
    out["cmf_20"] = chaikin_money_flow(high, low, close, volume, 20)

    # --- price structure -----------------------------------------------------
    out["return_1d"] = close.pct_change(1)
    out["return_5d"] = close.pct_change(5)
    out["return_10d"] = close.pct_change(10)
    out["return_20d"] = close.pct_change(20)

    out["high_20_dist"] = close / high.rolling(20).max() - 1
    out["low_20_dist"] = close / low.rolling(20).min() - 1
    out["high_52w_dist"] = close / high.rolling(252).max() - 1

    out["gap_pct"] = (open_ - close.shift(1)) / close.shift(1)
    candle_range = (high - low).replace(0, np.nan)
    out["body_pct"] = (close - open_).abs() / candle_range
    body_top = np.maximum(close, open_)
    body_bottom = np.minimum(close, open_)
    out["upper_wick_pct"] = (high - body_top) / candle_range
    out["lower_wick_pct"] = (body_bottom - low) / candle_range

    out["days_since_52w_high"] = _days_since_extreme(high, 252, "max")
    out["days_since_52w_low"] = _days_since_extreme(low, 252, "min")

    # Signed run length: +N is N consecutive up days, -N is N consecutive down
    # days — directional persistence, distinct from the magnitude-based
    # return_Nd/roc_N features above.
    day_sign = np.sign(close.diff()).fillna(0)
    run_id = (day_sign != day_sign.shift()).cumsum()
    out["streak"] = day_sign.groupby(run_id).cumcount().add(1) * day_sign

    # --- regime --------------------------------------------------------------
    out["adx_14"] = adx(high, low, close, 14)
    out["trend_strength"] = out["adx_14"] * np.sign(out["sma_10_50_cross"].fillna(0))
    # Is today's realised vol high or low relative to its own trailing year —
    # regime-relative rather than absolute, unlike volatility_20/atr_14_pct/
    # bb_width, which are all absolute-level measures.
    out["volatility_percentile_rank"] = out["volatility_20"].rolling(252).rank(pct=True)

    # --- market context: this stock vs. the benchmark index ------------------
    # merge_asof (backward) rather than a plain merge on ts: robust to the
    # stock and index not sharing an identical trading-day calendar (a
    # listing gap, a missing bar), and — because "backward" only ever matches
    # an index row at or before the stock's own row — this cannot pull in a
    # future index value even if the two calendars were ever misaligned.
    index_ctx = _index_context_frame(index_df, prefix="nifty")
    out = pd.merge_asof(out, index_ctx, on="ts", direction="backward")
    out["relative_strength_5d"] = out["return_5d"] - out["_nifty_return_5d"]
    out["relative_strength_20d"] = out["return_20d"] - out["_nifty_return_20d"]
    out = out.drop(columns=["_nifty_return_5d", "_nifty_return_20d"])

    # --- sector context: this stock vs. its own sector index -----------------
    sector_ctx = _index_context_frame(sector_df, prefix="sector")
    out = pd.merge_asof(out, sector_ctx, on="ts", direction="backward")
    out["sector_relative_strength_5d"] = out["return_5d"] - out["_sector_return_5d"]
    out["sector_relative_strength_20d"] = out["return_20d"] - out["_sector_return_20d"]
    out = out.drop(columns=["_sector_return_5d", "_sector_return_20d"])

    # --- macro: INDIA VIX ------------------------------------------------------
    vix_ctx = _vix_context_frame(vix_df)
    out = pd.merge_asof(out, vix_ctx, on="ts", direction="backward")

    # --- market breadth: cross-sectional across the watchlist ----------------
    out = pd.merge_asof(out, breadth_df[["ts", "breadth_pct_above_sma50", "breadth_advance_pct"]],
                         on="ts", direction="backward")

    # Infinities arise from the .replace(0, nan) guards above meeting a zero
    # numerator; treat them as missing rather than letting them reach the model.
    return out.replace([np.inf, -np.inf], np.nan)


def build_label(
    df: pd.DataFrame,
    horizon_days: int = 15,
    target_return: float = 0.08,
    stop_return: float = 0.04,
) -> pd.DataFrame:
    """Add the supervised target: did price reach +`target_return` **before**
    falling -`stop_return`, within `horizon_days` trading bars?

    This is a *barrier* label, and the "before" is the whole point. The
    previous version asked only whether the close was higher at bar
    t+horizon, which meant a stock that fell 8% and then recovered to +2%
    scored as a win — a trade the risk engine would have stopped out of days
    earlier. The model was being rewarded for trades the system would never
    have held.

    Three conventions, each chosen deliberately:

    * **The horizon is trading bars, not calendar days.** Rows here are
      trading sessions, so a shift of N rows is N trading days by
      construction. Note that `evaluate_pending_signals` measures its horizon
      in calendar days; the two are not the same number of sessions and
      should not be read as interchangeable.
    * **A same-bar touch of both barriers scores as a stop.** Daily bars
      cannot tell us which side was hit first, so the pessimistic reading
      wins. This matches the convention already fixed in
      `evaluate_pending_signals`.
    * **The final `horizon_days` rows are dropped**, even where a barrier was
      touched early enough to resolve. Keeping those would bias the tail of
      every series toward fast movers, because only the quick outcomes are
      knowable there.

    Uses a shifted *forward* window — the only place future data is allowed,
    because that is what a label is.
    """
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")

    out = df.copy()
    n = len(out)

    close = out["close"].to_numpy(dtype="float64")
    high = out["high"].to_numpy(dtype="float64")
    low = out["low"].to_numpy(dtype="float64")

    upper = close * (1.0 + target_return)
    lower = close * (1.0 - stop_return)

    # Bar offset at which each barrier is first touched. The sentinel is one
    # past the horizon, so "never touched" loses every comparison below.
    never = horizon_days + 1
    hit_target = np.full(n, never, dtype="int32")
    hit_stop = np.full(n, never, dtype="int32")

    for offset in range(1, horizon_days + 1):
        # Rows too close to the end have no bar at this offset; NaN compares
        # false against everything, so they are simply never touched.
        future_high = np.full(n, np.nan)
        future_low = np.full(n, np.nan)
        future_high[: n - offset] = high[offset:]
        future_low[: n - offset] = low[offset:]

        hit_target[(future_high >= upper) & (hit_target == never)] = offset
        hit_stop[(future_low <= lower) & (hit_stop == never)] = offset

    # Strictly before: an equal offset is the same-bar tie, which goes to the
    # stop, and two sentinels mean the window expired without touching either.
    out["target"] = (hit_target < hit_stop).astype(int)

    # Carried for diagnostics and for the dataset projection. It is the plain
    # close-to-close return at the horizon and is NOT what `target` measures —
    # the two disagree whenever a barrier was touched mid-window.
    out["future_close"] = out["close"].shift(-horizon_days)
    out["forward_return"] = out["future_close"] / out["close"] - 1

    return out.iloc[:-horizon_days]


def latest_feature_row(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    breadth_df: pd.DataFrame,
) -> pd.DataFrame | None:
    """The most recent fully-formed feature vector, ready for prediction.

    Returns None when indicators have not warmed up (a fresh instrument with
    under ~200 bars leaves the long moving averages undefined). Predicting on a
    partially-NaN vector is worse than not predicting at all.
    """
    featured = build_features(df, index_df, sector_df, vix_df, breadth_df)
    row = featured.iloc[[-1]][FEATURE_COLUMNS]
    return None if row.isna().to_numpy().any() else row
