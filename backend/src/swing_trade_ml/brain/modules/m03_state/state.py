"""One stock's state, in plain terms: its trend, how it has done against
NIFTY, and how far it is from its 52-week high. Pure."""

from __future__ import annotations

import pandas as pd

from swing_trade_ml.brain.contracts import StockState

RS_DAYS = 60
YEAR = 252


def stock_state(symbol: str, closes: pd.Series, index_closes: pd.Series) -> StockState:
    closes = closes.dropna().reset_index(drop=True)
    if len(closes) < 200:
        return StockState(symbol=symbol)
    last = float(closes.iloc[-1])
    sma50 = float(closes.tail(50).mean())
    sma200 = float(closes.tail(200).mean())
    if last > sma50 > sma200:
        trend = "up"
    elif last < sma50 < sma200:
        trend = "down"
    else:
        trend = "sideways"

    rel = None
    index_closes = index_closes.dropna().reset_index(drop=True)
    if len(closes) > RS_DAYS and len(index_closes) > RS_DAYS:
        stock_ret = last / float(closes.iloc[-RS_DAYS - 1]) - 1
        index_ret = float(index_closes.iloc[-1]) / float(index_closes.iloc[-RS_DAYS - 1]) - 1
        rel = round(stock_ret - index_ret, 4)

    high = float(closes.tail(YEAR).max())
    return StockState(
        symbol=symbol,
        trend=trend,
        rel_strength_vs_nifty=rel,
        dist_from_52w_high_pct=round(last / high - 1, 4) if high > 0 else None,
    )
