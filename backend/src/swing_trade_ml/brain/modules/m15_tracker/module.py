"""M15 · Trade tracker (plug-in to the state step, so it runs intraday too).

For each open holding with a known entry day: how many trading days in, the
return so far, and where that sits in the band of similar past trades
(track.py). "Similar" uses the situation key the stock had ON ITS ENTRY DAY
(M05's memory); with no match, the band of all past trades, said on the
card. At +5% (not yet halved) it attaches how often similar trades went on
to +8%. The decision engine turns drift and breakdown into MONITOR with what
changed; a stop hit is stated, never offered as a choice.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m04_situations.rules import label_days
from swing_trade_ml.brain.modules.m05_memory.cases import state_keys
from swing_trade_ml.brain.modules.m05_memory.recall import similar_cases, typical_path
from swing_trade_ml.brain.modules.m15_tracker.track import FIRST_TARGET, after_first_target, track
from swing_trade_ml.brain.reader import IST
from swing_trade_ml.core.config import settings
from swing_trade_ml.ml.features import atr

OVERALL = " (no close match; compared with all past trades)"


def _entry_key(bars: pd.DataFrame, market_label: str | None) -> dict | None:
    upto = bars.tail(260).reset_index(drop=True)
    if len(upto) < 200 or market_label is None:
        return None
    last = state_keys(upto, pd.Series(market_label, index=upto["day"])).iloc[-1]
    if any(last[p] is None for p in ("stock", "trend", "vol")):
        return None
    return {"market": market_label, "stock": last["stock"], "trend": last["trend"], "vol": last["vol"]}


@register_module
class Tracker(BrainModule):
    manifest = Manifest(
        id="M15",
        name="Trade tracker",
        step=Step.STATE,
        kind="plugin",
        version="1.0.0",
        reads=(),
        writes=("TrackPoint@1",),
        budget_s=15.0,
        intraday_budget_s=10.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        holdings = [h for h in view.holdings if h.opened_on is not None]
        if not holdings:
            return c.Contribution()
        reader = view.reader
        today = view.request.as_of.astimezone(IST).date()
        cases = reader.experience()
        known = cases[cases["outcome_day"] <= today] if len(cases) else cases
        nifty = reader.dated_closes(settings.BENCHMARK_INDEX_SYMBOL)
        labels = (
            label_days(nifty, reader.dated_closes("INDIA VIX"))["label"]
            if len(nifty)
            else pd.Series(dtype=object)
        )

        points = []
        for h in holdings:
            bars = reader.dated_bars(h.symbol)
            if bars.empty:
                continue
            before = bars[bars["day"] <= h.opened_on]
            since = bars[bars["day"] > h.opened_on]
            entry_label = (
                labels[labels.index <= h.opened_on].iloc[-1]
                if len(labels[labels.index <= h.opened_on])
                else None
            )
            key = _entry_key(before, None if entry_label == "unlabelled" else entry_label)
            found = similar_cases(known, key, today)[0] if key is not None and len(known) else known.iloc[0:0]
            overall = found.empty
            if overall:
                found = known
            band = typical_path(found, today) if len(found) else ()
            last_atr = atr(
                bars["high"].astype(float), bars["low"].astype(float), bars["close"].astype(float), 14
            )
            atr_pct = float(last_atr.iloc[-1] / bars["close"].iloc[-1]) if len(bars) >= 15 else None
            point = track(
                h.symbol,
                h.avg_price,
                list(zip(since["day"], since["close"].astype(float), strict=True)),
                h.stop,
                band,
                atr_pct,
            )
            note = ""
            if point.ret >= FIRST_TARGET and not h.scaled_out and len(found):
                note = after_first_target(found) or ""
            reason = point.reason + (OVERALL if overall and band and point.band_low is not None else "")
            points.append(replace(point, reason=reason, first_target_note=note))
        return c.Contribution(tracks=tuple(points))
