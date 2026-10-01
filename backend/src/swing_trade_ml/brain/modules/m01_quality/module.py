"""M01 · Data gateway and quality score.

Checks that the prices the brain is about to use are fresh, complete and
believable, for every stock in the run and for NIFTY, and reports how far
behind the side feeds (delivery, deals, FII/DII flows) are. A stock whose
data is not fresh can never be a TRADE (M07 refuses it; constitution C5),
and market-wide stale data stops new trades (constitution C2).
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m01_quality.quality import (
    assess_bars,
    expected_bar_day,
    summarise,
    trading_days_between,
)
from swing_trade_ml.core.config import settings

# Side feeds are published in the evening, so being one trading day behind
# the price bar is normal, not late.
FEED_TOLERANCE_DAYS = 1


@register_module
class DataGateway(BrainModule):
    manifest = Manifest(
        id="M01",
        name="Data gateway and quality score",
        step=Step.PERCEIVE,
        kind="step",
        version="1.0.0",
        reads=(),
        writes=("DataQuality@1",),
        budget_s=15.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        reader = view.reader
        expected = expected_bar_day(view.request.as_of)
        actions = reader.action_days()

        symbols = list(dict.fromkeys((*view.request.universe, *(h.symbol for h in view.holdings))))
        stocks = [
            assess_bars(symbol, reader.recent_bars(symbol), expected, actions.get(symbol, set()))
            for symbol in symbols
        ]

        benchmark_symbol = settings.BENCHMARK_INDEX_SYMBOL
        benchmark_bars = reader.recent_bars(benchmark_symbol)
        benchmark = (
            assess_bars(benchmark_symbol, benchmark_bars, expected, set())
            if not benchmark_bars.empty
            else None
        )

        feeds_behind: dict[str, int | None] = {}
        for name, latest in reader.feed_latest().items():
            feeds_behind[name] = (
                None
                if latest is None
                else max(0, trading_days_between(latest, expected) - FEED_TOLERANCE_DAYS)
            )

        overall = summarise(stocks, benchmark, feeds_behind)
        records = [*stocks, overall]
        if benchmark is not None:
            records.append(benchmark)
        return c.Contribution(quality=tuple(records))
