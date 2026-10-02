"""Rank sector indices against NIFTY and label their rotation.

Relative strength over a window = the sector index's return minus NIFTY's.
The 20-day (about a month) and 60-day (about three months) values give the
rotation quadrant:

    leading    stronger than NIFTY over both
    improving  stronger this month, after a weak three months
    weakening  weaker this month, after a strong three months
    lagging    weaker over both

Sectors rank by the 20-day value (then the 60-day, then name). A sector
without 61 bars of history is left out rather than ranked on a guess.
Pure: takes closing-price series that already end at the run's date.
"""

from __future__ import annotations

import pandas as pd

from swing_trade_ml.brain.contracts import SectorState

SHORT_DAYS = 20
LONG_DAYS = 60

# The opinion nudge per rotation: small, and never enough to decide alone.
TILT: dict[str, float] = {"leading": 0.1, "improving": 0.05, "weakening": -0.05, "lagging": -0.1}

SECTOR_NAMES: dict[str, str] = {
    "NIFTY BANK": "Banks",
    "NIFTY FIN SERVICE": "Financial services",
    "NIFTY CAPITAL MKT": "Capital markets",
    "NIFTY IT": "IT",
    "NIFTY AUTO": "Auto",
    "NIFTY FMCG": "FMCG (everyday goods)",
    "NIFTY CONSR DURBL": "Consumer durables",
    "NIFTY CONSUMPTION": "Consumption",
    "NIFTY PHARMA": "Pharma",
    "NIFTY HEALTHCARE": "Healthcare",
    "NIFTY METAL": "Metals",
    "NIFTY ENERGY": "Energy",
    "NIFTY REALTY": "Real estate",
    "NIFTY COMMODITIES": "Commodities and chemicals",
    "NIFTY INFRA": "Infrastructure",
}

_MEANING = {
    "leading": "stronger than NIFTY over 1 and 3 months",
    "improving": "stronger than NIFTY this month after a weak 3 months",
    "weakening": "weaker than NIFTY this month after a strong 3 months",
    "lagging": "weaker than NIFTY over 1 and 3 months",
}


def relative_strength(sector: pd.Series, nifty: pd.Series, days: int) -> float | None:
    if len(sector) <= days or len(nifty) <= days:
        return None

    def ret(s: pd.Series) -> float:
        return float(s.iloc[-1] / s.iloc[-1 - days] - 1)

    return ret(sector) - ret(nifty)


def rotation(rs20: float, rs60: float) -> str:
    if rs20 > 0:
        return "leading" if rs60 > 0 else "improving"
    return "weakening" if rs60 > 0 else "lagging"


def rank_sectors(closes: dict[str, pd.Series], nifty: pd.Series) -> list[SectorState]:
    scored = []
    for index, series in closes.items():
        rs20 = relative_strength(series, nifty, SHORT_DAYS)
        rs60 = relative_strength(series, nifty, LONG_DAYS)
        if rs20 is None or rs60 is None:
            continue
        scored.append((index, rs20, rs60))
    scored.sort(key=lambda t: (-t[1], -t[2], t[0]))
    return [
        SectorState(sector=index, rank=i, of_total=len(scored), strength_20d=rs20, rotation=rotation(rs20, rs60))
        for i, (index, rs20, rs60) in enumerate(scored, start=1)
    ]


def plain_name(index: str) -> str:
    return SECTOR_NAMES.get(index, index.removeprefix("NIFTY ").title())


def sector_line(s: SectorState) -> str:
    return (
        f"Sector: {plain_name(s.sector)}, ranked {s.rank} of {s.of_total}, {s.rotation} "
        f"({_MEANING.get(s.rotation, 'no clear direction')})."
    )
