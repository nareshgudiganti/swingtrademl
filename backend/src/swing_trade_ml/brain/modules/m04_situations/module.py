"""M04 · Situation recognition (the recognise step).

Puts a name on what the market is doing (rules.py), says when it looks
unlike any day in history (novelty.py), and gives every idea and holding a
plain trend label — "extended" when it is stretched far above its 50-day
average. M12 adds the tested chart setups; M13 the events.

A crash, a bear phase or an unknown market SUGGESTS going careful; the
shared `brain.market_mode.effective_mode` turns that into DEFENSIVE (never
bolder). Which labels suggest it is DEFENSIVE_LABELS in rules.py — see the
evidence note in docs/brain/BUILD_NOTES.md before changing it.

Episodes (episodes.py, store.py) are written after live nightly runs only.
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m04_situations.novelty import novelty, state_vectors
from swing_trade_ml.brain.modules.m04_situations.rules import market_situation
from swing_trade_ml.core.config import settings

EXTENDED_ABOVE_SMA50 = 0.15
_TREND_LABEL = {"up": "up-trend", "down": "down-trend"}


def _stock_situation(symbol: str, stock: c.StockState | None, snap: c.Snapshot | None) -> c.Situation | None:
    stretch = dict(snap.features).get("sma_50_ratio") if snap is not None and snap.features else None
    if stretch is not None and stretch > EXTENDED_ABOVE_SMA50:
        return c.Situation(
            scope="stock",
            subject=symbol,
            label="extended",
            confidence=0.6,
            evidence=(
                f"{symbol} is {stretch:.0%} above its 50-day average — stretched, prone to pull back.",
            ),
        )
    if stock is None or stock.trend == "unknown":
        return None
    label = _TREND_LABEL.get(stock.trend, "sideways")
    return c.Situation(
        scope="stock", subject=symbol, label=label, confidence=0.5, evidence=(f"{symbol}: {label}.",)
    )


@register_module
class SituationRecognition(BrainModule):
    manifest = Manifest(
        id="M04",
        name="Situation recognition",
        step=Step.RECOGNISE,
        kind="step",
        version="1.0.0",
        reads=("MarketState@1", "StockState@1", "Snapshot@1"),
        writes=("Situation@1",),
        budget_s=15.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        reader = view.reader
        nifty = reader.dated_closes(settings.BENCHMARK_INDEX_SYMBOL)
        vix = reader.dated_closes("INDIA VIX")
        label = market_situation(nifty, vix)
        evidence = list(label.evidence)
        unknown = False
        if label.label != "unlabelled":
            seen = novelty(state_vectors(nifty, vix))
            unknown = seen.is_unknown
            evidence.append(seen.line)
        market = c.Situation(
            scope="market",
            subject=settings.BENCHMARK_INDEX_SYMBOL,
            label=label.label,
            confidence=label.confidence,
            is_unknown=unknown,
            suggest_defensive=label.suggest_defensive or unknown,
            evidence=tuple(evidence),
        )
        symbols = dict.fromkeys((*view.request.universe, *(h.symbol for h in view.holdings)))
        stocks = tuple(
            s
            for s in (_stock_situation(sym, view.stocks.get(sym), view.snapshots.get(sym)) for sym in symbols)
            if s is not None
        )
        return c.Contribution(situations=(market, *stocks))
