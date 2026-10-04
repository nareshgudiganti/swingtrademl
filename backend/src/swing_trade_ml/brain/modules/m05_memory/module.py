"""M05 · Memory and experience (the remember step).

For every idea and holding: today's situation key (M04's market label, the
stock's trend, its last 20 days, its volatility — cases.py) and a recall of
similar past cases known by the run's date (recall.py): how often +8% came
before -4%, the band of results, the typical days and the day-by-day path
(M15 tracks holdings against it).

Starts in trial (SHADOW): on 46 unseen months recall ranked outcomes barely
better than chance (AUC 0.52), so it informs — with honest figures beside the
raw history — and does not steer decisions until it proves an edge.
"""

from __future__ import annotations

import pandas as pd

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m04_situations.rules import label_days
from swing_trade_ml.brain.modules.m05_memory.cases import state_keys
from swing_trade_ml.brain.modules.m05_memory.recall import recall
from swing_trade_ml.brain.reader import IST
from swing_trade_ml.core.config import settings

KEY_BARS = 260


def _market_label(view: ContextView) -> str | None:
    for s in view.situations:
        if s.scope == "market" and s.label != "unlabelled":
            return s.label
    reader = view.reader
    nifty = reader.dated_closes(settings.BENCHMARK_INDEX_SYMBOL)
    if nifty.empty:
        return None
    label = str(label_days(nifty, reader.dated_closes("INDIA VIX"))["label"].iloc[-1])
    return None if label == "unlabelled" else label


@register_module
class Memory(BrainModule):
    manifest = Manifest(
        id="M05",
        name="Memory and experience",
        step=Step.REMEMBER,
        kind="step",
        version="1.0.0",
        reads=("Situation@1", "StockState@1", "MarketState@1"),
        writes=("Recall@1",),
        budget_s=20.0,
        default_mode=Mode.SHADOW,
    )

    def run(self, view: ContextView) -> c.Contribution:
        market = _market_label(view)
        if market is None:
            return c.Contribution()
        reader = view.reader
        cases = reader.experience()
        if cases.empty:
            return c.Contribution()
        today = view.request.as_of.astimezone(IST).date()
        recalls = []
        for symbol in dict.fromkeys((*view.request.universe, *(h.symbol for h in view.holdings))):
            bars = reader.dated_bars(symbol).tail(KEY_BARS).reset_index(drop=True)
            if len(bars) < 200:
                continue
            last = state_keys(bars, pd.Series(market, index=bars["day"])).iloc[-1]
            if any(last[p] is None for p in ("stock", "trend", "vol")):
                continue
            key = {"market": market, "stock": last["stock"], "trend": last["trend"], "vol": last["vol"]}
            recalls.append(recall(cases, symbol, key, today))
        return c.Contribution(recalls=tuple(recalls))
