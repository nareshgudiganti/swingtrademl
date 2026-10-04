"""M12 · Stock brain (plug-in to the recognise step).

A specialist for each idea and holding: classic swing setups and
breakdowns (setups.py), delivery percentage and genuine big-investor deals
(signals.py), and a one-line profile of how the stock usually moves
(profile.py). It writes stock situations (shown in the why), the delivery
signal into the stock's state, and a `setup` modifier opinion that only
orders ideas and adds card lines — it never decides alone.

How much each signal moves the order is the WEIGHTS table, set from 5 years
of watch-list stocks (+8% before -4% within 15 trading days, any day 17.6%):
pullback 16.7%, breakout 16.4%, tight base 13.0%, breakdown 20.4% — none of
the classic setups beat a random day, so they carry no weight and stay off
the cards. Delivery at 1.2x its usual level reached 22.3%: +0.2. Deals could
not be tested (one day of data stored), so the build book's +0.2 / -0.2
stand until there is history. Re-weight here, nowhere else.

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
from swing_trade_ml.brain.modules.m13_news.calendar import read_calendar
from swing_trade_ml.brain.reader import IST

WEIGHTS: dict[str, float] = {
    "pullback in up-trend": 0.0,
    "breakout": 0.0,
    "base": 0.0,
    "breakdown": 0.0,
    "delivery high": 0.2,
    "institution buying": 0.2,
    "institution selling": -0.2,
}
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
        events = reader.event_rows(symbols)

        situations: list[c.Situation] = []
        stocks: list[c.StockState] = []
        opinions: list[c.Opinion] = []
        for symbol in symbols:
            bars = reader.ohlcv(symbol, 300)
            setups = find_setups(bars)
            if any(sit.label == "price reset" for sit in read_calendar(symbol, today, events, ()).situations):
                # A split or bonus drops the price by arithmetic; that is not a breakdown.
                setups = [s for s in setups if s.label != "breakdown"]
            signal, delivery_line = delivery_signal(delivery.get(symbol, []))
            deal_sign, deal_line = deal_signal(deals_by.get(symbol, []), today)
            profile = profile_line(bars)

            situations.extend(
                c.Situation(scope="stock", subject=symbol, label=s.label, confidence=0.6, evidence=(s.line,))
                for s in setups
            )
            if signal:
                stocks.append(c.StockState(symbol=symbol, delivery_signal=signal))

            signals = [s.label for s in setups]
            if signal == "high":
                signals.append("delivery high")
            if deal_sign:
                signals.append("institution buying" if deal_sign > 0 else "institution selling")
            weights = [WEIGHTS.get(name, 0.0) for name in signals]
            stance = min(MAX_BOOST, sum(w for w in weights if w > 0)) + sum(w for w in weights if w < 0)
            # Card lines: only signals that carry weight, plus the profile.
            lines = tuple(
                line
                for line in (
                    *(s.line for s in setups if WEIGHTS.get(s.label, 0.0) != 0.0),
                    delivery_line,
                    deal_line,
                    profile,
                )
                if line
            )
            if lines:
                opinions.append(
                    c.Opinion(source="setup", symbol=symbol, stance=stance, confidence=0.3, reasons=lines)
                )
        return c.Contribution(situations=tuple(situations), stocks=tuple(stocks), opinions=tuple(opinions))
