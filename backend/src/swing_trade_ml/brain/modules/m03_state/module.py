"""M03 · State engine.

Answers "what is the state right now?" in one place: the market's facts
(trend, swings, breadth, India VIX, FII flows — with the mode left for the
market brain M10 to decide), each stock's trend and strength, the account
(live runs only) and the system (halted or not).
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m03_state.state import stock_state
from swing_trade_ml.brain.modules.m10_market.judge import inputs_from, market_facts


@register_module
class StateEngine(BrainModule):
    manifest = Manifest(
        id="M03",
        name="State engine",
        step=Step.STATE,
        kind="step",
        version="1.0.0",
        reads=(),
        writes=("MarketState@1", "StockState@1", "PortfolioState@1", "SystemState@1"),
        budget_s=15.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        reader = view.reader
        reader.clear_context_cache()
        inputs = inputs_from(reader)
        market = c.MarketState(**market_facts(inputs))  # mode left open for M10

        symbols = dict.fromkeys((*view.request.universe, *(h.symbol for h in view.holdings)))
        stocks = tuple(
            stock_state(symbol, reader.ohlcv(symbol, 260)["close"], inputs.index_close) for symbol in symbols
        )

        numbers = reader.portfolio_numbers(view.request.book) or {}
        portfolio = c.PortfolioState(book=view.request.book, positions=view.holdings, **numbers)
        return c.Contribution(market=market, stocks=stocks, portfolio=portfolio, system=reader.system_state())
