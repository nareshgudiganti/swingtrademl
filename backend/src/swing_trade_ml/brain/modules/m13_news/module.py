"""M13 · News and events brain (plug-in to the recognise step).

Knows the calendar from official exchange data we already store (results
dates, corporate actions, ASM/GSM lists) — no scraping. For every idea and
holding it writes event situations ("results soon", "event blackout",
"price reset"), the stock's exchange restrictions, and an `event` modifier
opinion carrying plain card lines ("Results on 14 Oct."). The decision
engine's existing rules turn these into AVOID for new ideas; holdings only
get the lines. Off → only v1's avoid list (inside the risk check) protects.
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m13_news.calendar import read_calendar
from swing_trade_ml.brain.reader import IST


@register_module
class EventsBrain(BrainModule):
    manifest = Manifest(
        id="M13",
        name="News and events brain",
        step=Step.RECOGNISE,
        kind="plugin",
        version="1.0.0",
        reads=(),
        writes=("Situation@1", "StockState@1", "Opinion@1"),
        budget_s=10.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        symbols = tuple(dict.fromkeys((*view.request.universe, *(h.symbol for h in view.holdings))))
        if not symbols:
            return c.Contribution()
        reader = view.reader
        today = view.request.as_of.astimezone(IST).date()
        events, restrictions = reader.event_rows(symbols), reader.restriction_rows(symbols)

        situations: list[c.Situation] = []
        stocks: list[c.StockState] = []
        opinions: list[c.Opinion] = []
        for symbol in symbols:
            ev = read_calendar(symbol, today, events, restrictions)
            situations.extend(ev.situations)
            if ev.restrictions:
                stocks.append(c.StockState(symbol=symbol, restrictions=ev.restrictions))
            if ev.notes:
                opinions.append(
                    c.Opinion(source="event", symbol=symbol, stance=0.0, confidence=0.0, reasons=ev.notes)
                )
        return c.Contribution(situations=tuple(situations), stocks=tuple(stocks), opinions=tuple(opinions))
