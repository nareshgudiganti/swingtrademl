"""M12 · Stock brain (plug-in to the recognise step).

A specialist for each idea and holding: classic swing setups and
breakdowns (setups.py), delivery percentage and genuine big-investor deals
(signals.py), and a one-line profile of how the stock usually moves
(profile.py). It writes stock situations, the delivery signal into the
stock's state, and a `setup` modifier opinion — +0.2 per confirming signal
(at most +0.4), -0.2 for a breakdown and for institutional selling. The
opinion only orders ideas and adds card lines; it never decides alone, and
a breakdown makes the decision engine AVOID a new idea.

Starts in trial (SHADOW): its lines appear only in the trace until it is
switched on.
"""

from __future__ import annotations

from collections import defaultdict

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m12_stock.profile import profile_line
from swing_trade_ml.brain.modules.m12_stock.setups import find_setups
from swing_trade_ml.brain.modules.m12_stock.signals import deal_signal, delivery_signal
from swing_trade_ml.brain.reader import IST

STEP = 0.2
MAX_BOOST = 0.4


@register_module
class StockBrain(BrainModule):
    manifest = Manifest(
        id="M12",
        name="Stock brain",
        step=Step.RECOGNISE,
        kind="plugin",
        version="1.0.0",
        reads=(),
        writes=("Situation@1", "StockState@1", "Opinion@1"),
        budget_s=20.0,
        default_mode=Mode.SHADOW,
    )

    def run(self, view: ContextView) -> c.Contribution:
        if view.request.kind == "intraday":
            return c.Contribution()
        symbols = tuple(dict.fromkeys((*view.request.universe, *(h.symbol for h in view.holdings))))
        if not symbols:
            return c.Contribution()
        reader = view.reader
        today = view.request.as_of.astimezone(IST).date()
        delivery = reader.delivery_rows(symbols)
        deals_by: dict[str, list] = defaultdict(list)
        for d in reader.deal_rows(symbols):
            deals_by[d.symbol].append(d)

        situations: list[c.Situation] = []
        stocks: list[c.StockState] = []
        opinions: list[c.Opinion] = []
        for symbol in symbols:
            bars = reader.ohlcv(symbol, 300)
            setups = find_setups(bars)
            signal, delivery_line = delivery_signal(delivery.get(symbol, []))
            deal_sign, deal_line = deal_signal(deals_by.get(symbol, []), today)
            profile = profile_line(bars)

            situations.extend(
                c.Situation(scope="stock", subject=symbol, label=s.label, confidence=0.6, evidence=(s.line,))
                for s in setups
            )
            if signal:
                stocks.append(c.StockState(symbol=symbol, delivery_signal=signal))

            confirming = sum(s.confirming for s in setups) + (signal == "high") + (deal_sign > 0)
            against = sum(not s.confirming for s in setups) + (deal_sign < 0)
            lines = tuple(
                line for line in (*(s.line for s in setups), delivery_line, deal_line, profile) if line
            )
            if lines:
                opinions.append(
                    c.Opinion(
                        source="setup",
                        symbol=symbol,
                        stance=min(MAX_BOOST, STEP * confirming) - STEP * against,
                        confidence=0.3,
                        reasons=lines,
                    )
                )
        return c.Contribution(situations=tuple(situations), stocks=tuple(stocks), opinions=tuple(opinions))
