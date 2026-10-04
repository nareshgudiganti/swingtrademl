"""Is a stock's price data fresh, complete and believable?

Pure functions over plain bars, so every rule is tested exactly. The score
starts at 1 and each problem takes a fixed penalty off it; a stock is "fresh"
only when its newest bar is the one expected today and the score clears the
floor. Every problem is also a plain-English sentence, because the owner sees
these reasons on the decision cards.
"""

from __future__ import annotations

from datetime import date, datetime, time
from itertools import pairwise
from zoneinfo import ZoneInfo

import pandas as pd

from swing_trade_ml.brain.contracts import DataQuality
from swing_trade_ml.core.market_session import is_trading_day, trading_days_between
from swing_trade_ml.core.market_session import previous_trading_day as _previous_trading_day

IST = ZoneInfo("Asia/Kolkata")
INGEST_DONE = time(15, 40)  # v1's daily_ingest job; the day's bar exists after this

QUALITY_FLOOR = 0.6
MIN_BARS = 220  # what the model needs for its longest indicator
MAX_GAP_TRADING_DAYS = 3
SPIKE_MOVE = 0.20
MAX_STALE_SHARE = 0.2  # more than this share of stale stocks makes the market unfresh

PENALTY = {
    "behind_1": 0.5,
    "behind_2plus": 0.8,
    "short_history": 0.3,
    "gap": 0.2,
    "spike": 0.3,
    "zero_volume": 0.2,
    "impossible": 0.3,
}


def expected_bar_day(as_of: datetime) -> date:
    """The newest daily bar that should exist at `as_of`."""
    local = as_of.astimezone(IST)
    today = local.date()
    if is_trading_day(today) and local.time() >= INGEST_DONE:
        return today
    return _previous_trading_day(today)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def assess_bars(
    symbol: str,
    bars: pd.DataFrame,
    expected_day: date,
    action_days: set[date],
    min_bars: int = MIN_BARS,
) -> DataQuality:
    """`bars`: ascending, columns day (date), open, high, low, close, volume."""
    if bars.empty:
        return DataQuality(symbol=symbol, score=0.0, fresh=False, issues=("No price data for this stock.",))

    penalty = 0.0
    issues: list[str] = []
    days = list(bars["day"])
    last_day = days[-1]

    behind = trading_days_between(last_day, expected_day)
    if behind:
        penalty += PENALTY["behind_1"] if behind == 1 else PENALTY["behind_2plus"]
        issues.append(f"Last price is from {last_day:%d %b %Y}, {_plural(behind, 'trading day')} old.")

    if len(bars) < min_bars:
        penalty += PENALTY["short_history"]
        issues.append(f"Only {len(bars)} days of history (the model needs {min_bars}).")

    recent_days = days[-60:]
    widest = max((trading_days_between(a, b) for a, b in pairwise(recent_days)), default=0)
    if widest > MAX_GAP_TRADING_DAYS:
        penalty += PENALTY["gap"]
        issues.append(f"Recent prices have a gap of {widest} trading days.")

    last20 = bars.tail(21).reset_index(drop=True)
    moves = last20["close"].pct_change()
    spikes = [
        (last20.loc[i, "day"], moves[i])
        for i in range(1, len(last20))
        if abs(moves[i]) > SPIKE_MOVE and last20.loc[i, "day"] not in action_days
    ]
    if spikes:
        penalty += PENALTY["spike"]
        for day, move in spikes[:3]:
            issues.append(f"Price moved {abs(move):.0%} on {day:%d %b} with no split or bonus on record.")

    if (bars.tail(5)["volume"] <= 0).any():
        penalty += PENALTY["zero_volume"]
        issues.append("Zero trading volume in the last 5 days.")

    tail = bars.tail(20)
    impossible = (tail["high"] < tail["low"]) | (tail["close"] > tail["high"]) | (tail["close"] < tail["low"])
    if impossible.any():
        penalty += PENALTY["impossible"]
        bad_day = tail.loc[impossible, "day"].iloc[-1]
        issues.append(f"An impossible price bar on {bad_day:%d %b} (high, low and close do not fit).")

    score = round(max(0.0, 1.0 - penalty), 4)
    return DataQuality(
        symbol=symbol,
        score=score,
        fresh=behind == 0 and score >= QUALITY_FLOOR,
        last_bar_date=last_day.isoformat(),
        issues=tuple(issues),
    )


def summarise(
    stocks: list[DataQuality],
    benchmark: DataQuality | None,
    feeds_behind: dict[str, int | None],
) -> DataQuality:
    """The market-wide record ("*"): trustworthy only when the benchmark is
    fresh and no more than a fifth of the stocks are stale. Late side feeds
    (delivery, deals, flows) are reported but do not stop trading alone."""
    issues: list[str] = []
    fresh = True

    if benchmark is None:
        fresh = False
        issues.append("No NIFTY data, so the market cannot be judged.")
    elif not benchmark.fresh:
        fresh = False
        detail = benchmark.issues[0] if benchmark.issues else f"score {benchmark.score:.2f}"
        issues.append(f"NIFTY data is not fresh ({detail})")

    score = round(sum(q.score for q in stocks) / len(stocks), 4) if stocks else 0.0
    stale = [q for q in stocks if not q.fresh]
    if stocks and len(stale) / len(stocks) > MAX_STALE_SHARE:
        fresh = False
        issues.append(f"{len(stale)} of {len(stocks)} stocks have unreliable data.")
    if score < QUALITY_FLOOR:
        fresh = False

    for name, behind in sorted(feeds_behind.items()):
        if behind is None:
            issues.append(f"The {name} feed has no data yet.")
        elif behind > 0:
            issues.append(f"The {name} feed is {_plural(behind, 'trading day')} behind.")

    return DataQuality(
        symbol="*",
        score=score,
        fresh=fresh,
        last_bar_date=benchmark.last_bar_date if benchmark else None,
        issues=tuple(issues),
    )
