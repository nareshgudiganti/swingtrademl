"""The answer each step gives when no module in it works.

Fallbacks are deliberately simple and cautious. Together they make the empty
brain behave roughly like version 1 does today — the active model's score
against its buy level — while the constitution pass keeps that from turning
into a trade until the risk gate (M07) and the data gateway (M01) exist.

The risk step has no fallback. Its absence is handled by the constitution:
no risk gate means no new trades.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.module import Step
from swing_trade_ml.ml.market_context import classify_regime

# The locked trade rule: +8% target, -4% stop.
TARGET_PCT = 0.08
STOP_PCT = 0.04

_TREND = {"bullish": "up", "bearish": "down"}


def perceive(ctx: BrainContext) -> c.Contribution:
    snapshots = []
    for symbol in ctx.all_symbols:
        last = ctx.reader.last_close(symbol)
        if last is not None:
            bar_date, close = last
            snapshots.append(c.Snapshot(symbol=symbol, as_of=bar_date, close=float(close)))
    return c.Contribution(snapshots=tuple(snapshots))


def state(ctx: BrainContext) -> c.Contribution:
    closes = ctx.reader.index_closes()
    regime = classify_regime(closes if closes is not None else pd.Series(dtype=float))
    trend = _TREND.get(regime["regime"], "unknown")
    volatility = regime["volatility_level"]

    if trend == "up" and volatility != "elevated":
        mode = c.MarketMode.NORMAL
        reasons = ("NIFTY's 50-day average is above its 200-day average (up-trend).",)
    elif trend == "unknown":
        mode = c.MarketMode.DEFENSIVE
        reasons = ("Not enough NIFTY history to judge the trend, so the brain stays careful.",)
    elif trend == "down":
        mode = c.MarketMode.DEFENSIVE
        reasons = ("NIFTY's 50-day average is below its 200-day average (down-trend).",)
    else:
        mode = c.MarketMode.DEFENSIVE
        reasons = ("Market swings are larger than usual.",)

    return c.Contribution(
        market=c.MarketState(trend=trend, volatility=volatility, mode=mode, reasons=reasons),
        system=ctx.reader.system_state(),
        portfolio=c.PortfolioState(book=ctx.request.book, positions=ctx.holdings),
    )


def nothing(ctx: BrainContext) -> c.Contribution:
    return c.Contribution()


def reason(ctx: BrainContext) -> c.Contribution:
    """The active model's score only. Replays skip it: the model scores the
    latest bars, which would be look-ahead for a past date."""
    if not ctx.request.live:
        return c.Contribution()
    opinions = []
    for symbol in ctx.idea_symbols:
        scored = ctx.reader.model_probability(symbol)
        if scored is None:
            continue
        p, threshold, model = scored
        opinions.append(
            c.Opinion(
                source="model",
                symbol=symbol,
                stance=max(-1.0, min(1.0, 2 * p - 1)),
                confidence=min(1.0, abs(2 * p - 1)),
                probability=p,
                threshold=threshold,
                reasons=(
                    f"The active model ({model}) scores this stock {p:.0%}; "
                    f"its buy level is {threshold:.0%}.",
                ),
            )
        )
    return c.Contribution(opinions=tuple(opinions))


def _model_opinion(ctx: BrainContext, symbol: str) -> c.Opinion | None:
    return next((o for o in ctx.opinions if o.symbol == symbol and o.probability is not None), None)


def decide(ctx: BrainContext) -> c.Contribution:
    """Threshold map: score at or above the buy level (and not refused by the
    risk gate) → TRADE with the locked levels; otherwise WAIT. Holdings → HOLD."""
    decisions = []
    for symbol in ctx.idea_symbols:
        snap = ctx.snapshots.get(symbol)
        if snap is None:
            decisions.append(
                c.Decision(
                    symbol=symbol,
                    kind="idea",
                    word=c.IdeaWord.WAIT,
                    reasons=("No price data for this stock yet.",),
                )
            )
            continue
        opinion = _model_opinion(ctx, symbol)
        if opinion is None:
            why = (
                "Model scores are not replayed for past dates."
                if not ctx.request.live
                else "No model score is available for this stock today."
            )
            decisions.append(c.Decision(symbol=symbol, kind="idea", word=c.IdeaWord.WAIT, reasons=(why,)))
            continue
        p, threshold = opinion.probability, opinion.threshold or 0.5
        if p < threshold:
            decisions.append(
                c.Decision(
                    symbol=symbol,
                    kind="idea",
                    word=c.IdeaWord.WAIT,
                    confidence=p,
                    reasons=(f"Model score {p:.0%} is below the buy level {threshold:.0%}.",),
                )
            )
            continue
        verdict = ctx.verdicts.get(symbol)
        if verdict is not None and not verdict.allowed:
            decisions.append(
                c.Decision(
                    symbol=symbol,
                    kind="idea",
                    word=c.IdeaWord.WATCH,
                    confidence=p,
                    reasons=(f"Good score ({p:.0%}), but the risk check said no: {verdict.reason}",),
                )
            )
            continue
        close = snap.close
        decisions.append(
            c.Decision(
                symbol=symbol,
                kind="idea",
                word=c.IdeaWord.TRADE,
                confidence=p,
                entry_low=close,
                entry_high=close,
                target=round(close * (1 + TARGET_PCT), 2),
                stop=round(close * (1 - STOP_PCT), 2),
                qty=verdict.max_qty if verdict is not None else 0,
                horizon_days=ctx.request.horizon_days,
                reasons=(
                    *opinion.reasons,
                    f"Plan: target +8%, stop -4%, up to {ctx.request.horizon_days} trading days.",
                ),
            )
        )

    for holding in ctx.holdings:
        decisions.append(
            c.Decision(
                symbol=holding.symbol,
                kind="holding",
                word=c.HoldingWord.HOLD,
                reasons=(
                    "Holding reviews are not installed yet; "
                    "the existing exit rules still manage this position.",
                ),
            )
        )

    market = ctx.market
    mode = market.mode if market is not None else c.MarketMode.DEFENSIVE
    reasons = market.reasons if market is not None else ("Market state is unknown.",)
    banner = c.Banner(mode=mode, headline=reasons[0] if reasons else mode.value, reasons=reasons)
    return c.Contribution(decisions=tuple(decisions), banner=banner)


FALLBACKS: dict[Step, Callable[[BrainContext], c.Contribution]] = {
    Step.PERCEIVE: perceive,
    Step.STATE: state,
    Step.RECOGNISE: nothing,
    Step.REMEMBER: nothing,
    Step.REASON: reason,
    Step.RISK: nothing,  # no fallback: the constitution turns its absence into NO NEW TRADES
    Step.DECIDE: decide,
    Step.LEARN: nothing,
}
