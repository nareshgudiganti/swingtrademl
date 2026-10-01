"""M10 · Market brain (plug-in to the state step).

Decides the market mode — NORMAL, DEFENSIVE or NO NEW TRADES — with plain
reasons, from market data that ends at the run's date. The state engine (M03)
runs first and reports the facts with the mode left open; this fills it in.
When this module is off, the state fallback decides from the trend alone.
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m10_market.judge import inputs_from, judge


@register_module
class MarketBrain(BrainModule):
    manifest = Manifest(
        id="M10",
        name="Market brain",
        step=Step.STATE,
        kind="plugin",
        version="1.0.0",
        reads=(),
        writes=("MarketState@1",),
        budget_s=15.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        view.reader.clear_context_cache()
        return c.Contribution(market=judge(inputs_from(view.reader)))
