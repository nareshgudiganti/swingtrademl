"""M08 · Decision engine.

Gathers what the earlier steps know about each stock and holding, runs the
pure engine (draft → rules → opportunity notes) and writes the decisions and
the market banner. The rule list and every threshold live in rules.py and
policy.py, so behaviour changes there, not here. Anything this module leaves
out is filled by the decide fallback, and the constitution still runs last.
"""

from __future__ import annotations

from collections import defaultdict

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.market_mode import effective_mode
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m08_decide.engine import (
    HoldingFacts,
    IdeaFacts,
    decide_holding,
    decide_idea,
    opportunity_notes,
)
from swing_trade_ml.brain.modules.m08_decide.policy import DEFAULT_POLICY
from swing_trade_ml.brain.modules.m11_sector.module import sector_index_of
from swing_trade_ml.brain.modules.m12_stock.setups import find_setups
from swing_trade_ml.brain.opinions import modifier_notes, pick_opinion
from swing_trade_ml.core.config import settings


@register_module
class DecisionEngine(BrainModule):
    manifest = Manifest(
        id="M08",
        name="Decision engine",
        step=Step.DECIDE,
        kind="step",
        version="1.0.0",
        reads=(
            "Snapshot@1",
            "Opinion@1",
            "RiskVerdict@1",
            "DataQuality@1",
            "StockState@1",
            "Situation@1",
            "Recall@1",
            "MarketState@1",
            "TrackPoint@1",
        ),
        writes=("Decision@1", "Banner@1"),
        budget_s=10.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        policy = DEFAULT_POLICY
        market = view.market
        mode, suggested = effective_mode(market, view.situations)

        opinions: dict[str, list[c.Opinion]] = defaultdict(list)
        for o in view.opinions:
            opinions[o.symbol].append(o)
        situations: dict[str, list[c.Situation]] = defaultdict(list)
        for s in view.situations:
            if s.scope == "stock":
                situations[s.subject].append(s)

        held = {h.symbol for h in view.holdings}
        sectors = {s.sector: s for s in view.sectors.values()}

        def _sector_rank(symbol: str) -> int | None:
            idx = sector_index_of(symbol)
            if idx is None:
                return None
            st = sectors.get(idx)
            return st.rank if st is not None else None

        def _playbook_match(symbol: str) -> bool:
            if not settings.BRAIN_PLAYBOOK_GATE:
                return True
            bars = view.reader.ohlcv(symbol)
            if bars.empty:
                return False
            setups = find_setups(bars)
            return any(s.label in ("pullback in up-trend", "breakout") for s in setups)

        idea_facts = {
            symbol: IdeaFacts(
                symbol=symbol,
                snapshot=view.snapshots.get(symbol),
                opinion=pick_opinion(opinions.get(symbol, [])),
                verdict=view.verdicts.get(symbol),
                quality=view.quality.get(symbol),
                stock=view.stocks.get(symbol),
                situations=tuple(situations.get(symbol, [])),
                recall=view.recalls.get(symbol),
                market_mode=mode,
                notes=modifier_notes(opinions.get(symbol, [])),
                sector_rank=_sector_rank(symbol),
                playbook_match=_playbook_match(symbol),
            )
            for symbol in view.request.universe
            if symbol not in held
        }
        holding_facts = {
            h.symbol: HoldingFacts(
                holding=h,
                snapshot=view.snapshots.get(h.symbol),
                stock=view.stocks.get(h.symbol),
                market_mode=mode,
                notes=modifier_notes(opinions.get(h.symbol, [])),
                track=view.tracks.get(h.symbol),
            )
            for h in view.holdings
        }

        ideas = {s: decide_idea(f, policy) for s, f in idea_facts.items()}
        holdings = {s: decide_holding(f, policy) for s, f in holding_facts.items()}
        ideas, holdings = opportunity_notes(ideas, idea_facts, holdings, holding_facts)

        reasons = market.reasons if market is not None and market.reasons else ("Market state is unknown.",)
        if suggested:
            reasons = (suggested, *reasons)
        banner = c.Banner(mode=mode, headline=reasons[0], reasons=reasons)
        return c.Contribution(decisions=(*ideas.values(), *holdings.values()), banner=banner)
