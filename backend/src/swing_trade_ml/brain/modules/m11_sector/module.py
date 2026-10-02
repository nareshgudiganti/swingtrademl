"""M11 · Sector brain (plug-in to the state step).

Ranks the NSE sector indices against NIFTY (ranking.py) and gives each
stock in a ranked sector a small modifier opinion: a nudge in the order
ideas are judged, and a card line like "Sector: IT, ranked 3 of 15,
improving". It never decides a stock on its own (see brain/opinions.py).

Unmapped stocks (conglomerates, telecom) get nothing rather than a guess.
Off → no sector table and no tilt; M07's 25% sector cap still applies.
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import ContextView
from swing_trade_ml.brain.module import BrainModule, Manifest, Mode, Step, register_module
from swing_trade_ml.brain.modules.m11_sector.ranking import TILT, rank_sectors, sector_line
from swing_trade_ml.ml.sector_map import SECTOR_INDEX_MAP, get_sector_bucket


def sector_index_of(symbol: str) -> str | None:
    """The stock's sector index, or None when it has no real sector."""
    return SECTOR_INDEX_MAP.get(symbol.upper()) if get_sector_bucket(symbol) else None


@register_module
class SectorBrain(BrainModule):
    manifest = Manifest(
        id="M11",
        name="Sector brain",
        step=Step.STATE,
        kind="plugin",
        version="1.0.0",
        reads=(),
        writes=("SectorState@1", "Opinion@1"),
        budget_s=10.0,
        default_mode=Mode.ON,
    )

    def run(self, view: ContextView) -> c.Contribution:
        if view.request.kind == "intraday":
            return c.Contribution()
        reader = view.reader
        ranked = rank_sectors(reader.sector_closes(), reader.index_closes())
        if not ranked:
            return c.Contribution()
        by_index = {s.sector: s for s in ranked}

        opinions = []
        for symbol in dict.fromkeys((*view.request.universe, *(h.symbol for h in view.holdings))):
            sector = by_index.get(sector_index_of(symbol) or "")
            if sector is None:
                continue
            opinions.append(
                c.Opinion(
                    source="sector",
                    symbol=symbol,
                    stance=TILT.get(sector.rotation, 0.0),
                    confidence=0.3,
                    reasons=(sector_line(sector),),
                )
            )
        return c.Contribution(sectors=tuple(ranked), opinions=tuple(opinions))
